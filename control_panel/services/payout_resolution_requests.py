
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
    SellerPayoutResolution,
)


def request_payout_resolution(
    *,
    payout_id,
    investigation_id,
    requested_by,
    proposed_outcome,
    provider_reference,
    evidence,
):
    """
    Create a manual payout resolution request.

    Does not initiate transfers, change payout status,
    or release payout reservations.
    """

    if not requested_by.is_authenticated or not requested_by.is_superuser:
        return {
            "success": False,
            "message": "Only superusers can request payout resolution.",
        }

    if proposed_outcome not in {
        SellerPayoutResolution.OUTCOME_PAID,
        SellerPayoutResolution.OUTCOME_FAILED,
    }:
        return {
            "success": False,
            "message": "Invalid proposed outcome.",
        }

    try:
        with transaction.atomic():

            payout = SellerPayout.objects.select_for_update().get(
                pk=payout_id
            )

            if payout.status not in {
                SellerPayout.STATUS_PENDING,
                SellerPayout.STATUS_PROCESSING,
            }:
                return {
                    "success": False,
                    "message": "This payout is not awaiting resolution.",
                }

            investigation = SellerPayoutInvestigation.objects.get(
                pk=investigation_id,
                payout=payout,
            )

            if investigation.outcome != proposed_outcome:
                return {
                    "success": False,
                    "message": (
                        "Proposed outcome does not match "
                        "the investigation findings."
                    ),
                }

            if SellerPayoutResolution.objects.filter(
                payout=payout,
                status=SellerPayoutResolution.STATUS_PENDING,
            ).exists():
                return {
                    "success": False,
                    "message": (
                        "A pending resolution request already exists."
                    ),
                }

            resolution = SellerPayoutResolution.objects.create(
                payout=payout,
                investigation=investigation,
                requested_by=requested_by,
                proposed_outcome=proposed_outcome,
                provider_reference=provider_reference.strip(),
                evidence=evidence.strip(),
                status=SellerPayoutResolution.STATUS_PENDING,
            )

            return {
                "success": True,
                "message": "Resolution request created.",
                "resolution_id": resolution.pk,
            }

    except SellerPayout.DoesNotExist:
        return {
            "success": False,
            "message": "Payout not found.",
        }

    except SellerPayoutInvestigation.DoesNotExist:
        return {
            "success": False,
            "message": "Investigation not found for this payout.",
        }

    except (ValidationError, IntegrityError) as exc:
        return {
            "success": False,
            "message": f"Resolution request rejected: {exc}",
        }
