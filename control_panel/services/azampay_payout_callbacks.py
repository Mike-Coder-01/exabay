
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from control_panel.models import (
    SellerPayout,
    SellerPayoutAttempt,
)

from control_panel.services.azampay_payouts import (
    generate_disbursement_token,
    query_payout_status,
)


logger = logging.getLogger(__name__)


# Transfer attempt states that indicate the request
# may already have been sent to AzamPay.
SUBMITTED_ATTEMPT_STATUSES = (
    SellerPayoutAttempt.STATUS_SUBMITTING,
    SellerPayoutAttempt.STATUS_ACCEPTED,
    SellerPayoutAttempt.STATUS_UNKNOWN,
)


def verify_disbursement_callback(payload):
    """
    Verify an AzamPay disbursement callback.

    Security rules:
    1. The payout must exist.
    2. The payout must be pending or processing.
    3. A submitted transfer attempt must exist.
    4. Gateway references must match.
    5. AzamPay must independently confirm the transaction.
    6. Amount, provider and references must match.
    7. Database state must be rechecked under locks.
    8. Finalized payouts must not be finalized twice.

    This function never initiates or retries transfers.
    """

    reference = payload["initiatorReferenceId"]
    pg_reference = payload["pgReferenceId"]

    # --------------------------------------------------
    # STEP 1: Find the payout
    # --------------------------------------------------

    payout = SellerPayout.objects.get(
        order_reference=reference,
    )

    # Ignore callbacks for payouts that cannot
    # currently be updated.
    if payout.status not in (
        SellerPayout.STATUS_PENDING,
        SellerPayout.STATUS_PROCESSING,
    ):
        return "ignored"

    # --------------------------------------------------
    # STEP 2: Check transfer attempt
    # --------------------------------------------------

    # A reserved or claimed payout is not sufficient.
    # Its transfer attempt must have reached SUBMITTING
    # before a callback can finalize the payout.
    valid_attempt = SellerPayoutAttempt.objects.filter(
        payout=payout,
        status__in=SUBMITTED_ATTEMPT_STATUSES,
        submitting_at__isnull=False,
    ).exists()

    if not valid_attempt:
        logger.warning(
            "Ignoring AzamPay callback without a "
            "submitted transfer attempt: payout=%s",
            payout.pk,
        )
        return "ignored"

    # --------------------------------------------------
    # STEP 3: Check gateway reference
    # --------------------------------------------------

    if (
        payout.pg_reference_id
        and payout.pg_reference_id != pg_reference
    ):
        raise ValueError("AzamPay reference mismatch")

    # The provider must be the actual destination
    # provider recorded during payout preparation.
    bank_name = payout.channel_provider

    if not bank_name:
        raise ValueError("Missing payout provider")

    # --------------------------------------------------
    # STEP 4: Authenticate with AzamPay
    # --------------------------------------------------

    token = generate_disbursement_token()

    if not token:
        raise RuntimeError(
            "Unable to authenticate with AzamPay"
        )

    # --------------------------------------------------
    # STEP 5: Query the actual gateway status
    # --------------------------------------------------

    response = query_payout_status(
        token=token,
        pg_reference_id=pg_reference,
        bank_name=bank_name,
    )

    if response is None or response.status_code != 200:
        raise RuntimeError(
            "AzamPay status query failed"
        )

    result = response.json()

    if not isinstance(result, dict):
        raise ValueError(
            "Invalid AzamPay status response"
        )

    if result.get("success") is not True:
        raise RuntimeError(
            "AzamPay status query unsuccessful"
        )

    # --------------------------------------------------
    # STEP 6: Verify transaction identity
    # --------------------------------------------------

    if result.get("initiatorReferenceId") != reference:
        raise ValueError(
            "External reference mismatch"
        )

    if result.get("pgReferenceId") != pg_reference:
        raise ValueError(
            "Gateway reference mismatch"
        )

    # --------------------------------------------------
    # STEP 7: Verify amount
    # --------------------------------------------------

    try:
        verified_amount = Decimal(
            str(result["amount"])
        )

    except (
        KeyError,
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        raise ValueError(
            "Invalid verified amount"
        )

    if not verified_amount.is_finite():
        raise ValueError(
            "Non-finite verified amount"
        )

    if verified_amount != payout.amount:
        raise ValueError(
            "Payout amount mismatch"
        )

    # --------------------------------------------------
    # STEP 8: Verify payment provider
    # --------------------------------------------------

    verified_operator = str(
        result.get("operator", "")
    ).lower()

    if verified_operator != bank_name.lower():
        raise ValueError(
            "Payment provider mismatch"
        )

    # --------------------------------------------------
    # STEP 9: Verify transaction status
    # --------------------------------------------------

    verified_status = str(
        result.get("status", "")
    ).lower()

    if verified_status not in (
        "success",
        "failed",
        "failure",
        "pending",
    ):
        raise ValueError(
            "Unexpected payout status"
        )

    # --------------------------------------------------
    # STEP 10: Lock and recheck before updating
    # --------------------------------------------------

    with transaction.atomic():

        locked_payout = (
            SellerPayout.objects
            .select_for_update()
            .get(pk=payout.pk)
        )

        # A previous callback may already have
        # finalized the payout.
        if locked_payout.status not in (
            SellerPayout.STATUS_PENDING,
            SellerPayout.STATUS_PROCESSING,
        ):
            return "ignored"

        # Recheck the attempt while holding a lock.
        # This prevents relying only on an earlier
        # unlocked database read.
        locked_attempt = (
            SellerPayoutAttempt.objects
            .select_for_update()
            .filter(payout=locked_payout)
            .first()
        )

        if (
            locked_attempt is None
            or locked_attempt.status
            not in SUBMITTED_ATTEMPT_STATUSES
            or locked_attempt.submitting_at is None
        ):
            logger.warning(
                "AzamPay callback rejected after "
                "locking payout=%s: "
                "no valid submitted attempt",
                locked_payout.pk,
            )
            return "ignored"

        # --------------------------------------------------
        # STEP 11: Recheck gateway reference
        # --------------------------------------------------

        if (
            locked_payout.pg_reference_id
            and locked_payout.pg_reference_id != pg_reference
        ):
            raise ValueError(
                "Gateway reference changed"
            )

        # --------------------------------------------------
        # STEP 12: Recheck payout details
        # --------------------------------------------------

        if (
            locked_payout.order_reference != reference
            or locked_payout.amount != verified_amount
            or not locked_payout.channel_provider
            or locked_payout.channel_provider.lower()
            != bank_name.lower()
        ):
            raise ValueError(
                "Payout details changed"
            )

        # --------------------------------------------------
        # STEP 13: Save verified gateway information
        # --------------------------------------------------

        locked_payout.pg_reference_id = pg_reference

        locked_payout.fsp_reference_id = (
            result.get("fspReferenceId") or ""
        )

        locked_payout.gateway_response = result

        locked_payout.gateway_verified_at = (
            timezone.now()
        )

        # --------------------------------------------------
        # STEP 14: Update payout status
        # --------------------------------------------------

        if verified_status == "success":

            locked_payout.status = (
                SellerPayout.STATUS_SUCCESS
            )

            locked_payout.completed_at = (
                timezone.now()
            )

        elif verified_status in (
            "failed",
            "failure",
        ):

            locked_payout.status = (
                SellerPayout.STATUS_FAILED
            )

            locked_payout.completed_at = (
                timezone.now()
            )

        else:

            locked_payout.status = (
                SellerPayout.STATUS_PROCESSING
            )

        # --------------------------------------------------
        # STEP 15: Save payout
        # --------------------------------------------------

        locked_payout.save()

        logger.info(
            "AzamPay payout callback verified: "
            "payout=%s, status=%s, pg_reference=%s",
            locked_payout.pk,
            locked_payout.status,
            pg_reference,
        )

        return locked_payout.status