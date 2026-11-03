import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from control_panel.models import SellerPayout
from control_panel.services.azampay_payouts import (
    generate_disbursement_token,
    query_payout_status,
)

logger = logging.getLogger(__name__)


def verify_disbursement_callback(payload):
    reference = payload["initiatorReferenceId"]
    pg_reference = payload["pgReferenceId"]

    # First, find the payout using our unique reference.
    payout = SellerPayout.objects.get(
        order_reference=reference,
    )

    # Never verify an unexpected or uninitiated payout.
    if payout.status not in (
        SellerPayout.STATUS_PENDING,
        SellerPayout.STATUS_PROCESSING,
    ):
        return "ignored"

    # Prevent mismatched AzamPay references.
    if (
        payout.pg_reference_id
        and payout.pg_reference_id != pg_reference
    ):
        raise ValueError("AzamPay reference mismatch")

    # The payout initiation service must save the actual
    # destination provider before callbacks are enabled.
    bank_name = payout.channel_provider

    if not bank_name:
        raise ValueError("Missing payout provider")

    token = generate_disbursement_token()

    if not token:
        raise RuntimeError("Unable to authenticate with AzamPay")

    response = query_payout_status(
        token=token,
        pg_reference_id=pg_reference,
        bank_name=bank_name,
    )

    if response is None or response.status_code != 200:
        raise RuntimeError("AzamPay status query failed")

    result = response.json()

    if result.get("success") is not True:
        raise RuntimeError("AzamPay status query unsuccessful")

    # Check the verified transaction, not just callback values.
    if result.get("initiatorReferenceId") != reference:
        raise ValueError("External reference mismatch")

    if result.get("pgReferenceId") != pg_reference:
        raise ValueError("Gateway reference mismatch")

    try:
        verified_amount = Decimal(str(result["amount"]))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid verified amount")

    if not verified_amount.is_finite():
        raise ValueError("Non-finite verified amount")

    if verified_amount != payout.amount:
        raise ValueError("Payout amount mismatch")

    if str(result.get("operator", "")).lower() != bank_name.lower():
        raise ValueError("Payment provider mismatch")

    verified_status = str(result.get("status", "")).lower()

    # Only accept documented final statuses.
    if verified_status not in ("success", "failed", "failure", "pending"):
        raise ValueError("Unexpected payout status")

    # Lock and recheck before writing to the database.
    with transaction.atomic():
        locked_payout = SellerPayout.objects.select_for_update().get(
            pk=payout.pk
        )

        if locked_payout.status not in (
            SellerPayout.STATUS_PENDING,
            SellerPayout.STATUS_PROCESSING,
        ):
            return "ignored"

        if (
            locked_payout.pg_reference_id
            and locked_payout.pg_reference_id != pg_reference
        ):
            raise ValueError("Gateway reference changed")

        # Recheck values that may have changed while querying.
        if (
            locked_payout.order_reference != reference
            or locked_payout.amount != verified_amount
            or locked_payout.channel_provider.lower() != bank_name.lower()
        ):
            raise ValueError("Payout details changed")

        locked_payout.pg_reference_id = pg_reference
        locked_payout.fsp_reference_id = (
            result.get("fspReferenceId") or ""
        )
        locked_payout.gateway_response = result
        locked_payout.gateway_verified_at = timezone.now()

        if verified_status == "success":
            locked_payout.status = SellerPayout.STATUS_SUCCESS
            locked_payout.completed_at = timezone.now()

        elif verified_status in ("failed", "failure"):
            locked_payout.status = SellerPayout.STATUS_FAILED
            locked_payout.completed_at = timezone.now()

        else:
            locked_payout.status = SellerPayout.STATUS_PROCESSING

        locked_payout.save()

        return locked_payout.status