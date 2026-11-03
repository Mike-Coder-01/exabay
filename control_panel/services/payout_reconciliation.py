
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from control_panel.models import SellerPayout
from control_panel.services.azampay_payouts import (
    generate_disbursement_token,
    query_payout_status,
)


def reconcile_seller_payout(payout_id):
    """
    Verify an existing payout using AzamPay.

    Never initiates a new transfer.
    """

    payout = SellerPayout.objects.get(pk=payout_id)

    if payout.status in (
        SellerPayout.STATUS_SUCCESS,
        SellerPayout.STATUS_FAILED,
        SellerPayout.STATUS_REVERSED,
        SellerPayout.STATUS_REFUNDED,
    ):
        return {
            "success": False,
            "message": "Payout is already finalized.",
        }

    if payout.status not in (
        SellerPayout.STATUS_PENDING,
        SellerPayout.STATUS_PROCESSING,
    ):
        return {
            "success": False,
            "message": "Payout has not been initiated.",
        }

    if not payout.pg_reference_id:
        return {
            "success": False,
            "message": (
                "Gateway reference is missing. "
                "Manual reconciliation is required. "
                "Do not retry this transfer."
            ),
        }

    if not payout.channel_provider:
        return {
            "success": False,
            "message": "Payout provider is missing.",
        }

    token = generate_disbursement_token()

    if not token:
        return {
            "success": False,
            "message": "AzamPay authentication failed.",
        }

    try:
        response = query_payout_status(
            token=token,
            pg_reference_id=payout.pg_reference_id,
            bank_name=payout.channel_provider,
        )

        if response is None or response.status_code != 200:
            raise RuntimeError("Status query failed")

        verified = response.json()

        if not isinstance(verified, dict):
            raise ValueError("Invalid gateway response")

        if verified.get("success") is not True:
            raise ValueError("Transaction not verified")

        if (
            verified.get("initiatorReferenceId")
            != payout.order_reference
        ):
            raise ValueError("Payout reference mismatch")

        if (
            verified.get("pgReferenceId")
            != payout.pg_reference_id
        ):
            raise ValueError("Gateway reference mismatch")

        if (
            str(verified.get("operator", "")).strip().lower()
            != payout.channel_provider.strip().lower()
        ):
            raise ValueError("Provider mismatch")

        verified_amount = Decimal(
            str(verified.get("amount"))
        )

        if (
            not verified_amount.is_finite()
            or verified_amount <= 0
            or verified_amount != payout.amount
        ):
            raise ValueError("Payout amount mismatch")

        gateway_status = str(
            verified.get("status", "")
        ).strip().lower()

        status_mapping = {
            "success": SellerPayout.STATUS_SUCCESS,
            "failed": SellerPayout.STATUS_FAILED,
            "failure": SellerPayout.STATUS_FAILED,
            "pending": SellerPayout.STATUS_PROCESSING,
            "processing": SellerPayout.STATUS_PROCESSING,
        }

        if gateway_status not in status_mapping:
            raise ValueError("Unknown gateway status")

        new_status = status_mapping[gateway_status]

    except (
        ValueError,
        InvalidOperation,
        TypeError,
        RuntimeError,
    ) as exc:
        return {
            "success": False,
            "message": str(exc),
        }

    except Exception:
        return {
            "success": False,
            "message": "AzamPay verification unavailable.",
        }

    with transaction.atomic():
        locked = (
            SellerPayout.objects
            .select_for_update()
            .get(pk=payout_id)
        )

        # A callback may have finalized the payout
        # while the status query was running.
        if locked.status in (
            SellerPayout.STATUS_SUCCESS,
            SellerPayout.STATUS_FAILED,
            SellerPayout.STATUS_REVERSED,
            SellerPayout.STATUS_REFUNDED,
        ):
            return {
                "success": False,
                "message": "Payout already finalized.",
            }

        if locked.status not in (
            SellerPayout.STATUS_PENDING,
            SellerPayout.STATUS_PROCESSING,
        ):
            return {
                "success": False,
                "message": "Payout state changed.",
            }

        # Ensure the payout identity has not changed.
        if (
            locked.pg_reference_id != payout.pg_reference_id
            or locked.order_reference != payout.order_reference
            or locked.amount != payout.amount
            or locked.channel_provider != payout.channel_provider
        ):
            return {
                "success": False,
                "message": "Payout details changed.",
            }

        locked.status = new_status
        locked.gateway_response = verified
        locked.gateway_verified_at = timezone.now()
        locked.failure_reason = ""

        if new_status in (
            SellerPayout.STATUS_SUCCESS,
            SellerPayout.STATUS_FAILED,
        ):
            locked.completed_at = timezone.now()

        locked.save(
            update_fields=[
                "status",
                "gateway_response",
                "gateway_verified_at",
                "failure_reason",
                "completed_at",
                "updated_at",
            ]
        )

    return {
        "success": True,
        "message": "Payout reconciled successfully.",
        "status": new_status,
    }
