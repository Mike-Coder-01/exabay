
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from orders.models import OrderItem, SellerFulfillment
from users.models import SellerProfile

from control_panel.models import (
    SellerPayout,
    SellerPayoutReservation,
)
from control_panel.payout_services import generate_payout_reference
from control_panel.services.azampay_payouts import (
    get_azampay_provider,
)


def prepare_automatic_payout(fulfillment_id):
    """
    Prepare one payout for one eligible seller fulfillment.

    Database operations only.
    No external payment requests.
    """

    with transaction.atomic():

        # STEP 1: Identify the fulfillment and lock the seller.
        fulfillment_info = SellerFulfillment.objects.only(
            "id", "seller_id"
        ).get(pk=fulfillment_id)

        seller = (
            SellerProfile.objects
            .select_for_update()
            .select_related("user")
            .get(pk=fulfillment_info.seller_id)
        )

        # STEP 2: Lock and validate the fulfillment.
        fulfillment = (
            SellerFulfillment.objects
            .select_for_update()
            .select_related("order", "order__payment")
            .get(pk=fulfillment_id, seller=seller)
        )

        if not seller.is_verified:
            return None

        # Require shipment even for administrator release.
        if fulfillment.shipped_at is None:
            return None

        if not fulfillment.is_payout_eligible:
            return None

        # STEP 3: Retrieve seller payout settings.
        try:
            seller_settings = seller.settings
        except SellerProfile.settings.RelatedObjectDoesNotExist:
            return None

        phone = seller_settings.payout_phone_number.strip()
        account_name = seller_settings.payout_account_name.strip()

        if not phone or not account_name:
            return None

        bank_name = get_azampay_provider(seller_settings)

        # STEP 4: Select eligible, unpaid order items.
        # Exclude all items already associated with a payout,
        # including previewed, failed or completed payouts.
        existing_payout_items = Q(
            seller_payouts__isnull=False
        )

        items = list(
            OrderItem.objects
            .filter(
                fulfillment=fulfillment,
                product__seller=seller,
                order__payment__status="paid",
                seller_price__isnull=False,
                payout_reservation__isnull=True,
            )
            .exclude(existing_payout_items)
            .select_related("product")
            .order_by("pk")
            .distinct()
        )

        if not items:
            return None

        # STEP 5: Calculate payout amounts.
        # Seller receives the original seller price.
        amount = sum(
            (
                item.seller_price * item.quantity
                for item in items
            ),
            Decimal("0.00"),
        )

        # Buyer-facing total, including Exxabay markup.
        gross_amount = sum(
            (
                item.price * item.quantity
                for item in items
            ),
            Decimal("0.00"),
        )

        if amount <= 0:
            return None

        commission_amount = gross_amount - amount

        # STEP 6: Create the automatic payout.
        payout = SellerPayout.objects.create(
            seller=seller,
            created_by=None,
            gross_amount=gross_amount,
            commission_rate=Decimal("10.00"),
            commission_amount=commission_amount,
            amount=amount,
            currency="TZS",
            phone_number=phone,
            account_name=account_name,
            channel_provider=bank_name,
            order_reference=generate_payout_reference(),
            status=SellerPayout.STATUS_PENDING,
        )

        # STEP 7: Associate the order items with the payout.
        payout.order_items.set(items)

        # STEP 8: Reserve the order items to prevent
        # duplicate payouts.
        SellerPayoutReservation.objects.bulk_create([
            SellerPayoutReservation(
                payout=payout,
                order_item=item,
            )
            for item in items
        ])

        return payout
