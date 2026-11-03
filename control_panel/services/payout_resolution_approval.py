
from django.db import transaction
from django.utils import timezone

from control_panel.models import (
    SellerPayout,
    SellerPayoutResolution,
)


def decide_payout_resolution(
    *,
    resolution_id,
    decided_by,
    decision,
    approval_notes,
):
    """
    Approve or reject a manual payout resolution request.

    This function does NOT:
    - Initiate an AzamPay transfer
    - Change SellerPayout.status
    - Delete payout reservations
    """

    if not getattr(decided_by, "is_authenticated", False):
        return {
            "success": False,
            "message": "Authentication is required.",
        }

    if not decided_by.is_active or not decided_by.is_superuser:
        return {
            "success": False,
            "message": "Only active superusers can review resolutions.",
        }

    if decision not in {
        SellerPayoutResolution.STATUS_APPROVED,
        SellerPayoutResolution.STATUS_REJECTED,
    }:
        return {
            "success": False,
            "message": "Invalid resolution decision.",
        }

    if not isinstance(approval_notes, str) or not approval_notes.strip():
        return {
            "success": False,
            "message": "Approval notes are required.",
        }

    try:
        with transaction.atomic():

            resolution = (
                SellerPayoutResolution.objects
                .select_related("investigation")
                .select_for_update()
                .get(pk=resolution_id)
            )

            payout = (
                SellerPayout.objects
                .select_for_update()
                .get(pk=resolution.payout_id)
            )

            if resolution.status != SellerPayoutResolution.STATUS_PENDING:
                return {
                    "success": False,
                    "message": "This resolution has already been decided.",
                }

            if resolution.requested_by_id == decided_by.pk:
                return {
                    "success": False,
                    "message": "You cannot approve your own resolution request.",
                }

            if payout.status not in {
                SellerPayout.STATUS_PENDING,
                SellerPayout.STATUS_PROCESSING,
            }:
                return {
                    "success": False,
                    "message": "The payout is no longer awaiting resolution.",
                }

            if resolution.investigation.payout_id != payout.pk:
                return {
                    "success": False,
                    "message": "Investigation and payout do not match.",
                }

            if resolution.investigation.outcome != resolution.proposed_outcome:
                return {
                    "success": False,
                    "message": "Investigation outcome does not match the request.",
                }

            # Conditional update protects against a stale pending status.
            # Only one decision may transition this row from pending.
            updated = SellerPayoutResolution.objects.filter(
                pk=resolution.pk,
                status=SellerPayoutResolution.STATUS_PENDING,
                approved_by__isnull=True,
                decided_at__isnull=True,
            ).update(
                status=decision,
                approved_by=decided_by,
                approval_notes=approval_notes.strip(),
                decided_at=timezone.now(),
            )

            if updated != 1:
                return {
                    "success": False,
                    "message": "Resolution was already decided or changed.",
                }

            return {
                "success": True,
                "resolution_id": resolution.pk,
                "status": decision,
                "message": f"Resolution {decision} successfully.",
            }

    except SellerPayoutResolution.DoesNotExist:
        return {
            "success": False,
            "message": "Resolution request not found.",
        }

    except SellerPayout.DoesNotExist:
        return {
            "success": False,
            "message": "Associated payout not found.",
        }
