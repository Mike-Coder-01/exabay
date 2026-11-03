
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from users.models import SellerProfile
from control_panel.models import SellerPayout
from control_panel.services.payout_reconciliation import (
    reconcile_seller_payout,
)


class PayoutReconciliationTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.user = User.objects.create_user(
            username="reconcile_seller",
            email="reconcile@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=self.user,
            business_name="Reconciliation Test Seller",
            is_verified=True,
        )

        self.payout = SellerPayout.objects.create(
            seller=self.seller,
            amount=Decimal("1000.00"),
            gross_amount=Decimal("1000.00"),
            currency="TZS",
            phone_number="255700000000",
            account_name="Test Seller",
            channel_provider="Azampesa",
            order_reference="EXX-RECON-001",
            pg_reference_id="PG-RECON-001",
            status=SellerPayout.STATUS_PROCESSING,
        )

    def gateway_response(self, status="success", **overrides):
        payload = {
            "success": True,
            "initiatorReferenceId": "EXX-RECON-001",
            "pgReferenceId": "PG-RECON-001",
            "fspReferenceId": "FSP-RECON-001",
            "amount": "1000.00",
            "operator": "Azampesa",
            "status": status,
        }

        payload.update(overrides)

        response = Mock(status_code=200)
        response.json.return_value = payload

        return response

    @patch(
        "control_panel.services.payout_reconciliation."
        "query_payout_status"
    )
    @patch(
        "control_panel.services.payout_reconciliation."
        "generate_disbursement_token"
    )
    def test_successful_reconciliation(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-token"
        mock_query.return_value = self.gateway_response()

        result = reconcile_seller_payout(self.payout.pk)

        self.payout.refresh_from_db()

        self.assertTrue(result["success"])
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertIsNotNone(self.payout.completed_at)
        self.assertIsNotNone(self.payout.gateway_verified_at)

        mock_query.assert_called_once_with(
            token="fake-token",
            pg_reference_id="PG-RECON-001",
            bank_name="Azampesa",
        )

    @patch(
        "control_panel.services.payout_reconciliation."
        "query_payout_status"
    )
    @patch(
        "control_panel.services.payout_reconciliation."
        "generate_disbursement_token"
    )
    def test_failed_transaction_reconciliation(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-token"
        mock_query.return_value = self.gateway_response(
            status="failed"
        )

        result = reconcile_seller_payout(self.payout.pk)

        self.payout.refresh_from_db()

        self.assertTrue(result["success"])
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_FAILED,
        )
        self.assertIsNotNone(self.payout.completed_at)

    @patch(
        "control_panel.services.payout_reconciliation."
        "query_payout_status"
    )
    @patch(
        "control_panel.services.payout_reconciliation."
        "generate_disbursement_token"
    )
    def test_pending_transaction_remains_processing(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-token"
        mock_query.return_value = self.gateway_response(
            status="pending"
        )

        result = reconcile_seller_payout(self.payout.pk)

        self.payout.refresh_from_db()

        self.assertTrue(result["success"])
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )
        self.assertIsNone(self.payout.completed_at)
        self.assertIsNotNone(self.payout.gateway_verified_at)

    @patch(
        "control_panel.services.payout_reconciliation."
        "query_payout_status"
    )
    @patch(
        "control_panel.services.payout_reconciliation."
        "generate_disbursement_token"
    )
    def test_amount_mismatch_does_not_change_payout(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-token"
        mock_query.return_value = self.gateway_response(
            amount="500.00"
        )

        result = reconcile_seller_payout(self.payout.pk)

        self.payout.refresh_from_db()

        self.assertFalse(result["success"])
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )
        self.assertIsNone(self.payout.gateway_verified_at)

    @patch(
        "control_panel.services.payout_reconciliation."
        "query_payout_status"
    )
    @patch(
        "control_panel.services.payout_reconciliation."
        "generate_disbursement_token"
    )
    def test_missing_gateway_reference_requires_manual_review(
        self,
        mock_token,
        mock_query,
    ):
        self.payout.pg_reference_id = None
        self.payout.save(update_fields=["pg_reference_id"])

        result = reconcile_seller_payout(self.payout.pk)

        self.assertFalse(result["success"])
        self.assertIn(
            "manual reconciliation",
            result["message"].lower(),
        )

        mock_token.assert_not_called()
        mock_query.assert_not_called()

    @patch(
        "control_panel.services.payout_reconciliation."
        "query_payout_status"
    )
    @patch(
        "control_panel.services.payout_reconciliation."
        "generate_disbursement_token"
    )
    def test_duplicate_reconciliation_does_not_requery(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-token"
        mock_query.return_value = self.gateway_response()

        first_result = reconcile_seller_payout(self.payout.pk)

        self.payout.refresh_from_db()
        original_completed_at = self.payout.completed_at

        second_result = reconcile_seller_payout(self.payout.pk)

        self.payout.refresh_from_db()

        self.assertTrue(first_result["success"])
        self.assertFalse(second_result["success"])

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.payout.completed_at,
            original_completed_at,
        )

        mock_query.assert_called_once()
