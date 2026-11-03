
from django.db import transaction

from control_panel.models import SellerPayout
from control_panel.services.payout_reconciliation import (
    reconcile_seller_payout,
)


def resolve_payout_using_api(payout_id):
    """
    Resolve a payout using independently verified
    AzamPay transaction information.

    This function never initiates a new transfer.
    """

    try:
        payout = SellerPayout.objects.get(pk=payout_id)
    except SellerPayout.DoesNotExist:
        return {
            "success": False,
            "message": "Payout not found.",
        }

    # A completed payout must not be resolved again.
    terminal_statuses = {
        SellerPayout.STATUS_SUCCESS,
        SellerPayout.STATUS_FAILED,
        SellerPayout.STATUS_REVERSED,
        SellerPayout.STATUS_REFUNDED,
    }

    if payout.status in terminal_statuses:
        return {
            "success": False,
            "message": "This payout already has a final status.",
        }

    # Never attempt API resolution without the gateway reference.
    if not payout.pg_reference_id:
        return {
            "success": False,
            "message": (
                "Gateway reference missing. "
                "Manual investigation is required."
            ),
        }

    # Reuse the existing verified reconciliation service.
    result = reconcile_seller_payout(payout.pk)

    if not result["success"]:
        return result

    # Read the latest status after reconciliation.
    payout.refresh_from_db()

    return {
        "success": True,
        "status": payout.status,
        "message": (
            "Payout status verified with AzamPay. "
            f"Current status: {payout.status}."
        ),
    }
