
from django.db import transaction, IntegrityError
from django.utils import timezone

from control_panel.models import (
    SellerPayout,
    SellerPayoutResolution,
    SellerPayoutFinalization,
)


def finalize_manual_payout(
    *,
    resolution_id,
    finalized_by,
    verification_method,
    verification_evidence,
    provider_reference,
    provider_confirmed,
):
    """
    Manually finalize a payout after independent provider
    confirmation and two-administrator approval.

    Never sends money or removes payout reservations.
    """

    def fail(message):
        return {"success": False, "message": message}

    if not getattr(finalized_by, "is_authenticated", False):
        return fail("Authentication required.")

    if not finalized_by.is_active or not finalized_by.is_superuser:
        return fail("Only active superusers can finalize payouts.")

    if provider_confirmed is not True:
        return fail("Independent provider confirmation is required.")

    values = (
        verification_method,
        verification_evidence,
        provider_reference,
    )

    if any(
        not isinstance(value, str) or not value.strip()
        for value in values
    ):
        return fail("Complete provider verification evidence is required.")

    if len(verification_method.strip()) > 100:
        return fail("Verification method is too long.")

    if len(provider_reference.strip()) > 150:
        return fail("Provider reference is too long.")

    try:
        with transaction.atomic():
            # Read ID only; acquire payout lock first.
            resolution_ids = (
                SellerPayoutResolution.objects
                .filter(pk=resolution_id)
                .values("payout_id")
                .first()
            )

            if resolution_ids is None:
                return fail("Resolution not found.")

            payout = (
                SellerPayout.objects
                .select_for_update()
                .get(pk=resolution_ids["payout_id"])
            )

            resolution = (
                SellerPayoutResolution.objects
                .select_related("investigation")
                .select_for_update()
                .get(pk=resolution_id)
            )

            if resolution.payout_id != payout.pk:
                return fail("Resolution and payout do not match.")

            if resolution.status != SellerPayoutResolution.STATUS_APPROVED:
                return fail("Resolution has not been approved.")

            if resolution.approved_by_id is None:
                return fail("Resolution approval is incomplete.")

            if resolution.requested_by_id == resolution.approved_by_id:
                return fail("Invalid two-person approval.")

            if resolution.decided_at is None:
                return fail("Approval timestamp is missing.")

            if finalized_by.pk == resolution.requested_by_id:
                return fail("Requester cannot finalize their own resolution.")

            if payout.status not in {
                SellerPayout.STATUS_PENDING,
                SellerPayout.STATUS_PROCESSING,
            }:
                return fail("Payout is no longer awaiting finalization.")

            if SellerPayoutFinalization.objects.filter(
                payout=payout
            ).exists():
                return fail("Payout already manually finalized.")

            investigation = resolution.investigation

            if investigation.payout_id != payout.pk:
                return fail("Investigation belongs to another payout.")

            if investigation.outcome != resolution.proposed_outcome:
                return fail("Investigation outcome mismatch.")

            if (
                provider_reference.strip()
                != resolution.provider_reference.strip()
            ):
                return fail("Provider evidence reference mismatch.")

            outcome_mapping = {
                SellerPayoutResolution.OUTCOME_PAID:
                    SellerPayout.STATUS_SUCCESS,
                SellerPayoutResolution.OUTCOME_FAILED:
                    SellerPayout.STATUS_FAILED,
            }

            new_status = outcome_mapping.get(
                resolution.proposed_outcome
            )

            if new_status is None:
                return fail("Unsupported payout outcome.")

            now = timezone.now()

            SellerPayoutFinalization.objects.create(
                payout=payout,
                resolution=resolution,
                finalized_by=finalized_by,
                outcome=resolution.proposed_outcome,
                provider_reference=provider_reference.strip(),
                verification_method=verification_method.strip(),
                verification_evidence=verification_evidence.strip(),
            )

            payout.status = new_status
            payout.completed_at = now

            payout.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )

            return {
                "success": True,
                "status": new_status,
                "message": "Manual payout finalization recorded.",
            }

    except SellerPayout.DoesNotExist:
        return fail("Payout not found.")

    except SellerPayoutResolution.DoesNotExist:
        return fail("Resolution not found.")

    except IntegrityError:
        return fail("Payout finalization already exists.")
