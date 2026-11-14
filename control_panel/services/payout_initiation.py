
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
    create_mobile_money_payout,
)
from control_panel.services.payout_validation import (
    validate_payout_items,
)
from orders.models import SellerFulfillment
from users.models import SellerProfile


logger = logging.getLogger(__name__)


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

            attempt.error_message = (
                "AzamPay payout outcome unknown. "
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


def mark_payout_submitting(attempt_id):
    """
    Revalidate payout eligibility before submission.

    Lock order:
        seller -> payout -> fulfillments -> attempt
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

        SellerProfile.objects.select_for_update().get(
            pk=payout_info.seller_id
        )

        payout = (
            SellerPayout.objects
            .select_for_update()
            .select_related("seller")
            .get(pk=attempt_info.payout_id)
        )

        fulfillment_ids = sorted(
            set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            )
        )

        list(
            SellerFulfillment.objects
            .select_for_update()
            .filter(pk__in=fulfillment_ids)
            .order_by("pk")
        )

        attempt = (
            SellerPayoutAttempt.objects
            .select_for_update()
            .get(pk=attempt_id)
        )

        if attempt.status != SellerPayoutAttempt.STATUS_CLAIMED:
            return False

        if payout.status != SellerPayout.STATUS_PENDING:
            return False

        if payout.pg_reference_id or payout.initiated_at:
            return False

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
    """

    with transaction.atomic():
        payout_info = (
            SellerPayout.objects
            .only("id", "seller_id")
            .get(pk=payout_id)
        )

        SellerProfile.objects.select_for_update().get(
            pk=payout_info.seller_id
        )

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

        fulfillment_ids = sorted(
            set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            )
        )

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


def submit_claimed_payout(attempt_id):
    """
    Submit one claimed automatic payout to AzamPay.

    No automatic retries.
    Feature flag must be enabled.
    """

    if not getattr(
        settings,
        "AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED",
        False,
    ):
        logger.warning(
            "Automatic disbursements are disabled."
        )
        return False

    attempt = (
        SellerPayoutAttempt.objects
        .select_related("payout")
        .get(pk=attempt_id)
    )

    if attempt.status != SellerPayoutAttempt.STATUS_CLAIMED:
        return False

    payout = attempt.payout

    source = settings.AZAMPAY_DISBURSEMENT_SOURCE
    epoch_date = int(time.time())

    try:
        token = generate_disbursement_token()

        if not token:
            logger.error(
                "AzamPay authentication failed."
            )
            return False

        checksum = generate_disbursement_checksum(
            source_account=source["accountNumber"],
            destination_account=payout.phone_number,
            currency=payout.currency,
            amount=str(payout.amount),
            epoch_date=epoch_date,
            external_reference_id=payout.order_reference,
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

    # Only one worker may transition
    # CLAIMED -> SUBMITTING.
    if not mark_payout_submitting(attempt_id):
        return False

    # Check the automatic disbursement feature flag
    # again immediately before submission.
    if not getattr(
        settings,
        "AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED",
        False,
    ):
        logger.warning(
            "Automatic disbursements disabled before submission."
        )

        record_payout_submission_result(
            attempt_id,
            response=None,
        )

        return False

    # Do not automatically retry this request.
    try:
        response = create_mobile_money_payout(
            token=token,
            amount=payout.amount,
            order_reference=payout.order_reference,
            phone_number=payout.phone_number,
            source=source,
            destination_name=payout.account_name,
            bank_name=payout.channel_provider,
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

    record_payout_submission_result(
        attempt_id,
        response=response,
    )

    return True


def claim_reserved_manual_payout(payout_id):
    """
    Claim an already-reserved manual payout.

    Does not contact AzamPay.
    """

    with transaction.atomic():
        payout_info = (
            SellerPayout.objects
            .only("id", "seller_id")
            .get(pk=payout_id)
        )

        SellerProfile.objects.select_for_update().get(
            pk=payout_info.seller_id
        )

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

        fulfillment_ids = sorted(
            set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            )
        )

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

        return SellerPayoutAttempt.objects.create(
            payout=payout,
            status=SellerPayoutAttempt.STATUS_CLAIMED,
        )
