
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from users.models import SellerProfile, SellerSettings
from products.models import Product
from orders.models import (
    Order,
    OrderItem,
    Payment,
    SellerFulfillment,
)
from control_panel.models import (
    SellerPayout,
    SellerPayoutReservation,
)
from control_panel.services.automatic_payouts import (
    prepare_automatic_payout,
)
from unittest.mock import patch
from django.test import override_settings
from django.urls import reverse

class AutomaticPayoutTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.seller_user = User.objects.create_user(
            username="auto_payout_seller",
            email="auto-seller@example.com",
            password="TestPassword123!",
        )

        self.buyer = User.objects.create_user(
            username="auto_payout_buyer",
            email="auto-buyer@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            business_name="Automatic Test Seller",
            located_region="DSM",
            is_verified=True,
        )

        settings_obj, _ = SellerSettings.objects.get_or_create(
            seller=self.seller,
        )
        settings_obj.mobile_money_provider = (
            SellerSettings.MOBILE_PROVIDER_MPESA
        )
        settings_obj.payout_phone_number = "255700000000"
        settings_obj.payout_account_name = "Test Seller"
        settings_obj.save()

        self.product = Product.objects.create(
            seller=self.seller,
            name="Test Smartphone",
            description="Automatic payout test product",
            seller_price=Decimal("1000.00"),
            price=Decimal("1100.00"),
            stock=5,
        )

        self.order = Order.objects.create(
            user=self.buyer,
            total_amount=Decimal("1100.00"),
            status="paid",
        )

        self.payment = Payment.objects.create(
            order=self.order,
            amount=Decimal("1100.00"),
            method="mobile_money",
            status="paid",
            transaction_id="AUTO-PAYMENT-001",
        )

        self.fulfillment = SellerFulfillment.objects.create(
            order=self.order,
            seller=self.seller,
            shipped_at=timezone.now() - timedelta(hours=61),
            release_at=timezone.now() - timedelta(hours=1),
        )

        self.item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            fulfillment=self.fulfillment,
            quantity=1,
            price=Decimal("1100.00"),
            seller_price=Decimal("1000.00"),
        )

    def test_creates_payout_for_eligible_fulfillment(self):
        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNotNone(payout)
        self.assertEqual(payout.amount, Decimal("1000.00"))
        self.assertEqual(
            payout.gross_amount,
            Decimal("1100.00"),
        )
        self.assertEqual(
            payout.commission_amount,
            Decimal("100.00"),
        )
        self.assertEqual(
            payout.status,
            SellerPayout.STATUS_PENDING,
        )
        self.assertEqual(payout.channel_provider, "Vodacom")

        self.assertTrue(
            SellerPayoutReservation.objects.filter(
                payout=payout,
                order_item=self.item,
            ).exists()
        )

    def test_prevents_duplicate_payout(self):
        first = prepare_automatic_payout(self.fulfillment.pk)
        second = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(SellerPayout.objects.count(), 1)
        self.assertEqual(
            SellerPayoutReservation.objects.count(),
            1,
        )

    def test_unpaid_order_not_eligible(self):
        self.payment.status = "pending"
        self.payment.save(update_fields=["status"])

        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNone(payout)
        self.assertEqual(SellerPayout.objects.count(), 0)

    def test_active_dispute_blocks_payout(self):
        self.fulfillment.dispute_status = (
            SellerFulfillment.DISPUTE_OPEN
        )
        self.fulfillment.save(
            update_fields=["dispute_status"]
        )

        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNone(payout)
        self.assertEqual(SellerPayout.objects.count(), 0)

    def test_buyer_confirmation_allows_early_payout(self):
        self.fulfillment.shipped_at = timezone.now()
        self.fulfillment.release_at = (
            timezone.now() + timedelta(hours=60)
        )
        self.fulfillment.buyer_confirmed_at = timezone.now()
        self.fulfillment.save(
            update_fields=[
                "shipped_at",
                "release_at",
                "buyer_confirmed_at",
            ]
        )

        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNotNone(payout)
        self.assertEqual(payout.amount, Decimal("1000.00"))

    def test_before_60_hours_without_confirmation(self):
        self.fulfillment.shipped_at = timezone.now()
        self.fulfillment.release_at = (
            timezone.now() + timedelta(hours=60)
        )
        self.fulfillment.save(
            update_fields=["shipped_at", "release_at"]
        )

        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNone(payout)
        self.assertEqual(SellerPayout.objects.count(), 0)

    
    def test_buyer_confirmation_triggers_payout_preparation(self):
        """
        Verify that confirming receipt triggers payout
        preparation after the database transaction commits.
        """

        # The buyer should be able to confirm receipt
        # before the 60-hour deadline.
        self.fulfillment.shipped_at = timezone.now()
        self.fulfillment.release_at = (
            timezone.now() + timedelta(hours=60)
        )
        self.fulfillment.buyer_confirmed_at = None
        self.fulfillment.save(
            update_fields=[
                "shipped_at",
                "release_at",
                "buyer_confirmed_at",
            ]
        )

        self.client.force_login(self.buyer)

        with patch(
            "orders.views.prepare_automatic_payout"
        ) as mocked_prepare:

            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    # Replace with the actual URL name
                    # and keyword argument from orders/urls.py.
                    reverse(
                        "orders:confirm_received",
                        kwargs={
                            "fulfillment_id": self.fulfillment.pk
                        },
                    )
                )

            self.assertEqual(response.status_code, 302)

            mocked_prepare.assert_called_once_with(
                self.fulfillment.pk
            )

        self.fulfillment.refresh_from_db()

        self.assertIsNotNone(
            self.fulfillment.buyer_confirmed_at
        )


