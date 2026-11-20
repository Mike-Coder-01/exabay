
import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from control_panel.models import (
    SellerPayout,
    SellerPayoutAttempt,
)
from control_panel.services.azampay_payouts import (
    generate_disbursement_token,
    generate_disbursement_checksum,
    lookup_seller_name,
    validate_name_lookup_response,
    create_mobile_money_payout,
    _validate_transfer_amount,
)
from control_panel.services.payout_validation import (
    validate_payout_items,
)
from orders.models import SellerFulfillment

from users.models import SellerProfile, SellerSettings

from control_panel.services.azampay_payouts import (
    AZAMPAY_PROVIDER_MAP,
)


logger = logging.getLogger(__name__)


def payout_matches_verified_seller_account(payout):
    """
    Ensure the payout destination matches the seller's
    currently verified mobile-money account.

    Fail closed if settings are missing, unverified,
    or do not match the payout destination.
    """

    try:
        seller_settings = SellerSettings.objects.get(
            seller_id=payout.seller_id
        )

    except SellerSettings.DoesNotExist:
        logger.warning(
            "Payout %s blocked: seller settings missing.",
            payout.pk,
        )
        return False

    if not seller_settings.payout_account_verified:
        logger.warning(
            "Payout %s blocked: seller account is not verified.",
            payout.pk,
        )
        return False

    verified_phone = str(
        seller_settings.payout_phone_number or ""
    ).strip()

    payout_phone = str(
        payout.phone_number or ""
    ).strip()

    def normalize_phone(value):
        digits = "".join(
            char for char in str(value)
            if char.isdigit()
        )

        if digits.startswith("255") and len(digits) == 12:
            return digits[3:]

        if digits.startswith("0") and len(digits) == 10:
            return digits[1:]

        return digits

    if normalize_phone(verified_phone) != normalize_phone(
        payout_phone
    ):
        logger.warning(
            "Payout %s blocked: payout phone does not "
            "match seller's verified phone.",
            payout.pk,
        )
        return False

    verified_provider = (
        seller_settings.mobile_money_provider
    )

    expected_bank_name = AZAMPAY_PROVIDER_MAP.get(
        verified_provider
    )

    if not expected_bank_name:
        logger.warning(
            "Payout %s blocked: unsupported verified provider.",
            payout.pk,
        )
        return False

    if str(payout.channel_provider or "").strip().casefold() != (
        expected_bank_name.strip().casefold()
    ):
        logger.warning(
            "Payout %s blocked: provider does not match "
            "seller's verified provider.",
            payout.pk,
        )
        return False

    def normalize_name(value):
        return " ".join(
            str(value or "").casefold().split()
        )

    verified_name = normalize_name(
        seller_settings.payout_account_name
    )

    payout_name = normalize_name(
        payout.account_name
    )

    if not verified_name or verified_name != payout_name:
        logger.warning(
            "Payout %s blocked: payout name does not "
            "match seller's verified account name.",
            payout.pk,
        )
        return False

    return True

def describe_azampay_submission_error(response):
    """
    Return a sanitized diagnostic message.

    Never include raw gateway messages, account numbers,
    tokens, checksums, or personal information.
    """
    if response is None:
        return "No HTTP response received"

    status = response.status_code

    try:
        payload = response.json()
    except (ValueError, TypeError):
        return f"AzamPay HTTP {status}: non-JSON response"

    if not isinstance(payload, dict):
        return f"AzamPay HTTP {status}: unexpected response format"

    import re

    categories = set()

    for key in ("message", "error", "errors"):
        value = payload.get(key)

        if not isinstance(value, str):
            continue

        words = set(
            re.findall(r"[a-z]+", value.lower())
        )

        if {"insufficient", "balance"} <= words:
            categories.add("insufficient balance")
        if "checksum" in words:
            categories.add("checksum validation")
        if "signature" in words:
            categories.add("signature validation")
        if "amount" in words:
            categories.add("amount validation")
        if "destination" in words or "account" in words:
            categories.add("account validation")
        if "duplicate" in words:
            categories.add("duplicate reference")
        if "unauthorized" in words or "forbidden" in words:
            categories.add("authorization")
        if "currency" in words:
            categories.add("currency validation")

    reason = ", ".join(sorted(categories)) if categories else "unspecified rejection"

    return f"AzamPay HTTP {status}: {reason}"

def record_payout_submission_result(
    attempt_id,
    *,
    response=None,
):
    """
    Record the outcome of one AzamPay submission.

    Does not contact AzamPay.
    Does not retry transfers.
    Does not mark a payout successful.
    """

    payload = {}

    if response is not None:
        try:
            parsed = response.json()

            if isinstance(parsed, dict):
                payload = parsed

        except (ValueError, TypeError):
            pass

    accepted = (
        response is not None
        and response.status_code in (200, 201)
        and payload.get("success") is True
        and isinstance(payload.get("pgReferenceId"), str)
        and bool(payload.get("pgReferenceId").strip())
    )

    with transaction.atomic():
        attempt_info = (
            SellerPayoutAttempt.objects
            .only("id", "payout_id")
            .get(pk=attempt_id)
        )

        payout = (
            SellerPayout.objects
            .select_for_update()
            .get(pk=attempt_info.payout_id)
        )

        attempt = (
            SellerPayoutAttempt.objects
            .select_for_update()
            .get(pk=attempt_id)
        )

        if attempt.status != SellerPayoutAttempt.STATUS_SUBMITTING:
            logger.warning(
                "Payout result recording rejected: "
                "attempt_id=%s, status=%s",
                attempt.pk,
                attempt.status,
            )
            return False

        if accepted:
            pg_reference = payload["pgReferenceId"].strip()

            if (
                payout.pg_reference_id
                and payout.pg_reference_id != pg_reference
            ):
                attempt.status = SellerPayoutAttempt.STATUS_UNKNOWN
                attempt.error_message = (
                    "Gateway reference conflict. "
                    "Manual reconciliation required."
                )

            else:
                attempt.status = SellerPayoutAttempt.STATUS_ACCEPTED
                attempt.error_message = ""
                payout.pg_reference_id = pg_reference

                # A verified callback may already have
                # finalized the payout.
                if payout.status == SellerPayout.STATUS_PENDING:
                    payout.status = SellerPayout.STATUS_PROCESSING
                    payout.gateway_response = payload

                if payout.initiated_at is None:
                    payout.initiated_at = timezone.now()

                payout.save(
                    update_fields=[
                        "pg_reference_id",
                        "status",
                        "gateway_response",
                        "initiated_at",
                        "updated_at",
                    ]
                )

        else:
            attempt.status = SellerPayoutAttempt.STATUS_UNKNOWN

            diagnostic = describe_azampay_submission_error(response)

            attempt.error_message = (
                f"{diagnostic}. "
                "Manual reconciliation required. "
                "Do not retry automatically."
            )

            # Preserve callback-verified final outcomes.
            if payout.status == SellerPayout.STATUS_PENDING:
                payout.failure_reason = attempt.error_message

                payout.save(
                    update_fields=[
                        "failure_reason",
                        "updated_at",
                    ]
                )

        # IMPORTANT:
        # These operations must execute for both
        # ACCEPTED and UNKNOWN outcomes.
        attempt.completed_at = timezone.now()

        attempt.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
            ]
        )

        return True




def mark_payout_submitting(attempt_id, verified_details=None):
    """
    Revalidate payout eligibility before submission.

    If verified_details is provided, ensure the payout
    still matches the details verified by NameLookup.

    Lock order:
        seller -> SellerSettings -> payout
        -> fulfillments -> attempt
    """

    with transaction.atomic():
        attempt_info = (
            SellerPayoutAttempt.objects
            .only("id", "payout_id")
            .get(pk=attempt_id)
        )

        payout_info = (
            SellerPayout.objects
            .only("id", "seller_id")
            .get(pk=attempt_info.payout_id)
        )

        # 1. Lock seller.
        SellerProfile.objects.select_for_update().get(
            pk=payout_info.seller_id
        )

        # 2. Lock current seller payout settings.
        list(
            SellerSettings.objects
            .select_for_update()
            .filter(seller_id=payout_info.seller_id)
        )

        # 3. Lock payout.
        payout = (
            SellerPayout.objects
            .select_for_update()
            .select_related("seller")
            .get(pk=attempt_info.payout_id)
        )

        # 4. Verify destination against the seller's
        # currently verified mobile-money account.
        if not payout_matches_verified_seller_account(payout):
            logger.warning(
                "Payout %s blocked: seller payout account "
                "is not currently verified or does not match.",
                payout.pk,
            )
            return False

        fulfillment_ids = sorted(
            set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            )
        )

        # 5. Lock fulfilments.
        list(
            SellerFulfillment.objects
            .select_for_update()
            .filter(pk__in=fulfillment_ids)
            .order_by("pk")
        )

        # 6. Lock attempt.
        attempt = (
            SellerPayoutAttempt.objects
            .select_for_update()
            .get(pk=attempt_id)
        )

        if attempt.status != SellerPayoutAttempt.STATUS_CLAIMED:
            return False

        # Block unresolved NameLookup failures.
        if attempt.error_message in {
            "recipient_verification_failed",
            "recipient_lookup_unavailable",
        }:
            logger.warning(
                "Payout %s blocked: unresolved NameLookup failure.",
                payout.pk,
            )
            return False

        if payout.status != SellerPayout.STATUS_PENDING:
            return False

        if payout.pg_reference_id or payout.initiated_at:
            return False

        # Ensure payout details have not changed
        # since NameLookup verification.
        if verified_details is not None:
            current_details = {
                "phone_number": payout.phone_number,
                "channel_provider": payout.channel_provider,
                "account_name": payout.account_name,
                "amount": payout.amount,
                "currency": payout.currency,
                "order_reference": payout.order_reference,
            }

            if current_details != verified_details:
                logger.warning(
                    "Payout %s blocked: payout details changed "
                    "after recipient verification.",
                    payout.pk,
                )
                return False

        # Revalidate reserved order items.
        error = validate_payout_items(
            payout,
            require_reservations=True,
        )

        if error:
            logger.warning(
                "Payout %s blocked before submission: %s",
                payout.pk,
                error,
            )
            return False

        # Only one worker can transition this attempt.
        attempt.status = SellerPayoutAttempt.STATUS_SUBMITTING
        attempt.submitting_at = timezone.now()

        attempt.save(
            update_fields=[
                "status",
                "submitting_at",
            ]
        )

        return True


def claim_payout_for_initiation(payout_id):
    """
    Atomically claim a prepared payout.

    Does not contact AzamPay.
    A payout can be claimed only once.
    Requires the seller's currently verified payout account.
    """

    with transaction.atomic():
        payout_info = (
            SellerPayout.objects
            .only("id", "seller_id")
            .get(pk=payout_id)
        )

        # 1. Lock the seller profile.
        SellerProfile.objects.select_for_update().get(
            pk=payout_info.seller_id
        )

        # 2. Lock the seller's payout settings.
        list(
            SellerSettings.objects
            .select_for_update()
            .filter(seller_id=payout_info.seller_id)
        )

        # 3. Lock the payout.
        payout = (
            SellerPayout.objects
            .select_for_update()
            .select_related("seller")
            .get(pk=payout_id)
        )

        if payout.status != SellerPayout.STATUS_PENDING:
            logger.info(
                "Payout %s is not pending.",
                payout_id,
            )
            return None

        if payout.pg_reference_id or payout.initiated_at:
            logger.warning(
                "Payout %s has already been initiated.",
                payout_id,
            )
            return None

        if SellerPayoutAttempt.objects.filter(
            payout=payout
        ).exists():
            logger.warning(
                "Payout %s has already been claimed.",
                payout_id,
            )
            return None

        # 4. Verify the current seller payout account.
        if not payout_matches_verified_seller_account(payout):
            logger.warning(
                "Payout %s rejected: seller payout account "
                "is not currently verified or does not match.",
                payout_id,
            )
            return None

        fulfillment_ids = sorted(
            set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            )
        )

        # 5. Lock fulfilments.
        list(
            SellerFulfillment.objects
            .select_for_update()
            .filter(pk__in=fulfillment_ids)
            .order_by("pk")
        )

        error = validate_payout_items(
            payout,
            require_reservations=True,
        )

        if error:
            logger.warning(
                "Payout %s rejected: %s",
                payout_id,
                error,
            )
            return None

        attempt = SellerPayoutAttempt.objects.create(
            payout=payout,
            status=SellerPayoutAttempt.STATUS_CLAIMED,
        )

        logger.info(
            "Payout %s claimed, attempt %s.",
            payout_id,
            attempt.pk,
        )

        return attempt


def record_name_lookup_failure(attempt_id, reason):
    """
    Record a failed recipient verification.

    No transfer has been submitted.
    Keep the attempt CLAIMED and block progression
    until the verification issue is resolved.
    """

    allowed_reasons = {
        "recipient_verification_failed",
        "recipient_lookup_unavailable",
    }

    if reason not in allowed_reasons:
        reason = "recipient_verification_failed"

    with transaction.atomic():
        attempt = (
            SellerPayoutAttempt.objects
            .select_for_update()
            .get(pk=attempt_id)
        )

        if attempt.status != SellerPayoutAttempt.STATUS_CLAIMED:
            return False

        attempt.error_message = reason

        attempt.save(
            update_fields=["error_message"]
        )

        return True


def submit_claimed_payout(attempt_id):
    """
    Submit one claimed automatic payout to AzamPay.

    Workflow:
        1. Check automatic disbursement feature flag.
        2. Retrieve the claimed payout.
        3. Capture payout details.
        4. Generate authentication token and checksum.
        5. Verify recipient using NameLookup.
        6. Recheck automatic disbursement feature flag.
        7. Revalidate payout details under database locks.
        8. Transition CLAIMED -> SUBMITTING.
        9. Submit the transfer using verified details.
       10. Record the submission result.

    No automatic retries.
    """

    # 1. Ensure automatic disbursements are enabled.
    if not getattr(
        settings,
        "AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED",
        False,
    ):
        logger.warning(
            "Automatic disbursements are disabled."
        )
        return False

    # 2. Retrieve the claimed payout attempt.
    attempt = (
        SellerPayoutAttempt.objects
        .select_related("payout")
        .get(pk=attempt_id)
    )

    if attempt.status != SellerPayoutAttempt.STATUS_CLAIMED:
        return False

    # Block unresolved recipient verification failures.
    if attempt.error_message in {
        "recipient_verification_failed",
        "recipient_lookup_unavailable",
    }:
        logger.warning(
            "Payout attempt %s has an unresolved "
            "recipient verification failure.",
            attempt_id,
        )
        return False

    payout = attempt.payout

    # 3. Capture payout details before NameLookup.
    # These values must remain unchanged until submission.
    verified_details = {
        "phone_number": payout.phone_number,
        "channel_provider": payout.channel_provider,
        "account_name": payout.account_name,
        "amount": payout.amount,
        "currency": payout.currency,
        "order_reference": payout.order_reference,
    }

    source = settings.AZAMPAY_DISBURSEMENT_SOURCE
    epoch_date = int(time.time())

    # 4. Generate token and prepare checksum.
    try:
        token = generate_disbursement_token()

        if not token:
            logger.error(
                "AzamPay authentication failed for payout %s.",
                payout.pk,
            )
            return False

        validated_amount = _validate_transfer_amount(
            verified_details["amount"]
        )

        checksum = generate_disbursement_checksum(
            source_account=source["accountNumber"],
            destination_account=verified_details["phone_number"],
            currency=verified_details["currency"],
            amount=str(int(validated_amount)),
            epoch_date=epoch_date,
            external_reference_id=verified_details["order_reference"],
            public_key_pem=(
                settings.AZAMPAY_DISBURSEMENT_PUBLIC_KEY
            ),
        )

    except Exception:
        logger.exception(
            "Could not prepare payout %s.",
            payout.pk,
        )
        return False

    # 5. Verify recipient details before submitting money.
    try:
        lookup_response = lookup_seller_name(
            token=token,
            bank_name=verified_details["channel_provider"],
            account_number=verified_details["phone_number"],
            checksum=checksum,
        )

        recipient_verified = validate_name_lookup_response(
            response=lookup_response,
            expected_account_number=verified_details["phone_number"],
            expected_bank_name=verified_details["channel_provider"],
            expected_account_name=verified_details["account_name"],
        )

    except Exception:
        record_name_lookup_failure(
            attempt_id,
            "recipient_lookup_unavailable",
        )

        logger.exception(
            "NameLookup request failed for payout %s. "
            "Transfer was not submitted.",
            payout.pk,
        )
        return False

    if not recipient_verified:
        record_name_lookup_failure(
            attempt_id,
            "recipient_verification_failed",
        )

        logger.warning(
            "NameLookup verification failed for payout %s. "
            "Transfer was not submitted.",
            payout.pk,
        )
        return False

    logger.info(
        "NameLookup verification successful for payout %s.",
        payout.pk,
    )

    # 6. Recheck the feature flag BEFORE changing
    # the attempt to SUBMITTING.
    if not getattr(
        settings,
        "AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED",
        False,
    ):
        logger.warning(
            "Automatic disbursements disabled after "
            "NameLookup for payout %s. "
            "Transfer was not submitted.",
            payout.pk,
        )

        # Keep the attempt CLAIMED.
        # No gateway transfer request has been made.
        return False

    # 7. Revalidate eligibility and verified details.
    # 8. Only one worker can transition CLAIMED -> SUBMITTING.
    if not mark_payout_submitting(
        attempt_id,
        verified_details=verified_details,
    ):
        logger.warning(
            "Payout %s could not transition to SUBMITTING.",
            payout.pk,
        )
        return False

    # 9. Submit using the verified payout snapshot.
    # Never automatically retry this request.
    #
    # After transitioning to SUBMITTING, do not cancel
    # based on a feature-flag change. The gateway
    # submission outcome must be recorded or reconciled.
    try:
        response = create_mobile_money_payout(
            token=token,
            amount=verified_details["amount"],
            order_reference=verified_details["order_reference"],
            phone_number=verified_details["phone_number"],
            source=source,
            destination_name=verified_details["account_name"],
            bank_name=verified_details["channel_provider"],
            transfer_type="MobileMoney",
            checksum=checksum,
            date_in_epoch=epoch_date,
        )

    except Exception:
        logger.exception(
            "AzamPay submission outcome unknown: payout=%s",
            payout.pk,
        )
        response = None

    # 10. Record the gateway submission result.
    record_payout_submission_result(
        attempt_id,
        response=response,
    )

    return True



def claim_reserved_manual_payout(payout_id):
    """
    Claim an already-reserved manual payout.

    Does not contact AzamPay.
    Requires the seller's currently verified payout account.
    """

    with transaction.atomic():
        payout_info = (
            SellerPayout.objects
            .only("id", "seller_id")
            .get(pk=payout_id)
        )

        # 1. Lock the seller profile.
        SellerProfile.objects.select_for_update().get(
            pk=payout_info.seller_id
        )

        # 2. Lock the seller's payout settings.
        list(
            SellerSettings.objects
            .select_for_update()
            .filter(seller_id=payout_info.seller_id)
        )

        # 3. Lock the payout.
        payout = (
            SellerPayout.objects
            .select_for_update()
            .select_related("seller")
            .get(pk=payout_id)
        )

        if payout.status != SellerPayout.STATUS_PENDING:
            return None

        if (
            payout.pg_reference_id
            or payout.initiated_at
            or SellerPayoutAttempt.objects.filter(
                payout=payout
            ).exists()
        ):
            return None

        # 4. Verify the current seller payout account.
        if not payout_matches_verified_seller_account(payout):
            logger.warning(
                "Manual payout %s rejected: seller payout account "
                "is not currently verified or does not match.",
                payout.pk,
            )
            return None

        fulfillment_ids = sorted(
            set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            )
        )

        # 5. Lock fulfilments.
        list(
            SellerFulfillment.objects
            .select_for_update()
            .filter(pk__in=fulfillment_ids)
            .order_by("pk")
        )

        error = validate_payout_items(
            payout,
            require_reservations=True,
        )

        if error:
            logger.warning(
                "Manual payout %s cannot be claimed: %s",
                payout.pk,
                error,
            )
            return None

        attempt = SellerPayoutAttempt.objects.create(
            payout=payout,
            status=SellerPayoutAttempt.STATUS_CLAIMED,
        )

        logger.info(
            "Manual payout %s claimed, attempt %s.",
            payout.pk,
            attempt.pk,
        )

        return attempt
