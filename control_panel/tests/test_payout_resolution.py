
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from users.models import SellerProfile
from control_panel.models import SellerPayout
from control_panel.services.payout_resolution import (
    resolve_payout_using_api,
)


class PayoutResolutionTests(TestCase):

    def setUp(self):
        User = get_user_model()

        user = User.objects.create_user(
            username="resolution_seller",
            email="resolution@example.com",
            password="TestPassword123!",
        )

        seller = SellerProfile.objects.create(
            user=user,
            business_name="Resolution Seller",
            is_verified=True,
        )

        self.payout = SellerPayout.objects.create(
            seller=seller,
            gross_amount=Decimal("55000.00"),
            commission_amount=Decimal("5000.00"),
            amount=Decimal("50000.00"),
            currency="TZS",
            phone_number="255700000000",
            account_name="Resolution Seller",
            channel_provider="Azampesa",
            order_reference="EXX-RESOLVE-001",
            pg_reference_id="PG-RESOLVE-001",
            status=SellerPayout.STATUS_PROCESSING,
        )

    @patch(
        "control_panel.services.payout_resolution."
        "reconcile_seller_payout"
    )
    def test_api_resolution_calls_reconciliation(
        self,
        mock_reconcile,
    ):
        mock_reconcile.return_value = {
            "success": True,
            "status": "processing",
        }

        result = resolve_payout_using_api(self.payout.pk)

        self.assertTrue(result["success"])
        mock_reconcile.assert_called_once_with(self.payout.pk)

    @patch(
        "control_panel.services.payout_resolution."
        "reconcile_seller_payout"
    )
    def test_missing_reference_blocks_resolution(
        self,
        mock_reconcile,
    ):
        self.payout.pg_reference_id = None
        self.payout.save(update_fields=["pg_reference_id"])

        result = resolve_payout_using_api(self.payout.pk)

        self.assertFalse(result["success"])
        mock_reconcile.assert_not_called()

    @patch(
        "control_panel.services.payout_resolution."
        "reconcile_seller_payout"
    )
    def test_completed_payout_cannot_be_resolved_again(
        self,
        mock_reconcile,
    ):
        self.payout.status = SellerPayout.STATUS_SUCCESS
        self.payout.save(update_fields=["status"])

        result = resolve_payout_using_api(self.payout.pk)

        self.assertFalse(result["success"])
        mock_reconcile.assert_not_called()

    @patch(
        "control_panel.services.payout_resolution."
        "reconcile_seller_payout"
    )
    def test_failed_reconciliation_does_not_resolve(
        self,
        mock_reconcile,
    ):
        mock_reconcile.return_value = {
            "success": False,
            "message": "AzamPay response mismatch.",
        }

        result = resolve_payout_using_api(self.payout.pk)

        self.assertFalse(result["success"])

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )
