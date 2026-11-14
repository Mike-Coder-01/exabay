
from decimal import Decimal

from control_panel.models import SellerPayoutReservation


def validate_payout_items(payout, *, require_reservations=False):
    """
    Validate the payout before initiating a transfer.

    Returns:
        None when valid.
        An error message when invalid.
    """

    items = list(
        payout.order_items.select_related(
            "order",
            "order__payment",
            "fulfillment",
            "product",
        ).order_by("pk")
    )

    if not items:
        return "This payout contains no order items."

    if not payout.seller.is_verified:
        return "The seller is not verified."

    if payout.currency != "TZS" or payout.amount <= 0:
        return "Invalid payout amount or currency."

    if not all([
        payout.account_name.strip(),
        payout.phone_number.strip(),
        payout.channel_provider.strip(),
    ]):
        return "The payout destination is incomplete."

    expected_amount = Decimal("0.00")

    for item in items:
        if item.product.seller_id != payout.seller_id:
            return "An item belongs to another seller."

        if item.fulfillment_id is None:
            return "An item has no fulfillment record."

        if item.fulfillment.seller_id != payout.seller_id:
            return "Fulfillment seller mismatch."

        if item.fulfillment.shipped_at is None:
            return "The fulfillment has not been shipped."

        if not item.fulfillment.is_payout_eligible:
            return (
                f"Order item #{item.pk} is not eligible "
                "for payout."
            )

        payment = getattr(item.order, "payment", None)

        if payment is None or payment.status != "paid":
            return "The order payment is not confirmed."

        if item.seller_price is None:
            return "An item has no seller price."

        expected_amount += item.seller_price * item.quantity

    if expected_amount != payout.amount:
        return "The payout amount does not match seller earnings."

    if require_reservations:
        item_ids = {item.pk for item in items}

        reserved_ids = set(
            SellerPayoutReservation.objects.filter(
                payout=payout,
                order_item_id__in=item_ids,
            ).values_list("order_item_id", flat=True)
        )

        if reserved_ids != item_ids:
            return "Payout reservations are incomplete."

    return None