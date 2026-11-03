
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from users.models import SellerProfile
from control_panel.models import SellerPayout


class AzamPayCallbackTests(TestCase):

    def setUp(self):
        self.url = reverse(
            "control_panel:azampay_disbursement_callback"
        )

        User = get_user_model()

        self.user = User.objects.create_user(
            username="test_azam_seller",
            email="azamseller@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=self.user,
            business_name="AzamPay Test Shop",
            located_region="DSM",
            is_verified=True,
        )

        self.payout = SellerPayout.objects.create(
            seller=self.seller,
            amount=Decimal("1000.00"),
            gross_amount=Decimal("1000.00"),
            commission_amount=Decimal("0.00"),
            currency="TZS",
            phone_number="255700000000",
            account_name="Test Seller",
            order_reference="EXX-TEST-001",
            pg_reference_id="PG-TEST-001",
            channel_provider="Azampesa",
            status=SellerPayout.STATUS_PROCESSING,
        )

    def callback_payload(self):
        return {
            "initiatorReferenceId": "EXX-TEST-001",
            "pgReferenceId": "PG-TEST-001",
            "operator": "Azampesa",
            "amount": "1000",
            "status": "success",
        }

    # --------------------------------------------------
    # TEST 1: Reject unknown payout reference
    # --------------------------------------------------

    def test_unknown_reference_is_rejected(self):
        payload = self.callback_payload()

        payload["initiatorReferenceId"] = "EXX-UNKNOWN-TEST"

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )

    # --------------------------------------------------
    # TEST 2: Successful AzamPay disbursement
    # --------------------------------------------------

    @patch("control_panel.views.query_payout_status")
    @patch("control_panel.views.generate_disbursement_token")
    def test_successful_disbursement_callback(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-test-token"

        mock_query.return_value = Mock(status_code=200)

        mock_query.return_value.json.return_value = {
            "success": True,
            "initiatorReferenceId": "EXX-TEST-001",
            "pgReferenceId": "PG-TEST-001",
            "fspReferenceId": "FSP-TEST-001",
            "amount": "1000",
            "operator": "Azampesa",
            "status": "success",
        }

        response = self.client.post(
            self.url,
            data=self.callback_payload(),
            content_type="application/json",
        )

        self.payout.refresh_from_db()

        print("\nSUCCESSFUL CALLBACK TEST")
        print("HTTP status:", response.status_code)
        print("Response:", response.json())
        print("Payout status:", self.payout.status)
        print("FSP reference:", self.payout.fsp_reference_id)
        print("Completed at:", self.payout.completed_at)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )

        self.assertEqual(
            self.payout.fsp_reference_id,
            "FSP-TEST-001",
        )

        self.assertIsNotNone(self.payout.completed_at)
        self.assertIsNotNone(self.payout.gateway_verified_at)

        mock_token.assert_called_once()
        mock_query.assert_called_once()

    # --------------------------------------------------
    # TEST 3: Reject mismatched payout amount
    # --------------------------------------------------

    @patch("control_panel.views.query_payout_status")
    @patch("control_panel.views.generate_disbursement_token")
    def test_rejects_mismatched_amount(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-test-token"

        mock_query.return_value = Mock(status_code=200)

        mock_query.return_value.json.return_value = {
            "success": True,
            "initiatorReferenceId": "EXX-TEST-001",
            "pgReferenceId": "PG-TEST-001",
            "fspReferenceId": "FSP-TEST-001",
            "amount": "500",
            "operator": "Azampesa",
            "status": "success",
        }

        response = self.client.post(
            self.url,
            data=self.callback_payload(),
            content_type="application/json",
        )

        self.payout.refresh_from_db()

        print("\nMISMATCHED AMOUNT TEST")
        print("HTTP status:", response.status_code)
        print("Response:", response.json())
        print("Payout status:", self.payout.status)

        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )

        self.assertIsNone(self.payout.completed_at)
        self.assertIsNone(self.payout.gateway_verified_at)

        mock_query.assert_called_once()

    # --------------------------------------------------
    # TEST 4: Handle duplicate successful callbacks
    # --------------------------------------------------

    @patch("control_panel.views.query_payout_status")
    @patch("control_panel.views.generate_disbursement_token")
    def test_duplicate_success_callback(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-test-token"

        mock_query.return_value = Mock(status_code=200)

        mock_query.return_value.json.return_value = {
            "success": True,
            "initiatorReferenceId": "EXX-TEST-001",
            "pgReferenceId": "PG-TEST-001",
            "fspReferenceId": "FSP-TEST-001",
            "amount": "1000",
            "operator": "Azampesa",
            "status": "success",
        }

        # First callback
        first_response = self.client.post(
            self.url,
            data=self.callback_payload(),
            content_type="application/json",
        )

        self.payout.refresh_from_db()

        first_completed_at = self.payout.completed_at
        first_verified_at = self.payout.gateway_verified_at

        # Second callback for the same transaction
        second_response = self.client.post(
            self.url,
            data=self.callback_payload(),
            content_type="application/json",
        )

        self.payout.refresh_from_db()

        print("\nDUPLICATE CALLBACK TEST")
        print("First response:", first_response.status_code)
        print("Second response:", second_response.status_code)
        print("Final payout status:", self.payout.status)
        print("Completed at:", self.payout.completed_at)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )

        self.assertEqual(
            self.payout.completed_at,
            first_completed_at,
        )

        self.assertEqual(
            self.payout.gateway_verified_at,
            first_verified_at,
        )

        self.assertEqual(
            self.payout.fsp_reference_id,
            "FSP-TEST-001",
        )

        mock_token.assert_called_once()
        mock_query.assert_called_once()

    # --------------------------------------------------
    # TEST 5: Handle failed AzamPay disbursement
    # --------------------------------------------------

    @patch("control_panel.views.query_payout_status")
    @patch("control_panel.views.generate_disbursement_token")
    def test_failed_disbursement_callback(
        self,
        mock_token,
        mock_query,
    ):
        mock_token.return_value = "fake-test-token"

        mock_query.return_value = Mock(status_code=200)

        mock_query.return_value.json.return_value = {
            "success": True,
            "initiatorReferenceId": "EXX-TEST-001",
            "pgReferenceId": "PG-TEST-001",
            "fspReferenceId": "FSP-FAILED-001",
            "amount": "1000",
            "operator": "Azampesa",
            "status": "failed",
        }

        payload = self.callback_payload()
        payload["status"] = "failed"

        response = self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
        )

        self.payout.refresh_from_db()

        print("\nFAILED DISBURSEMENT TEST")
        print("HTTP status:", response.status_code)
        print("Response:", response.json())
        print("Payout status:", self.payout.status)
        print("Completed at:", self.payout.completed_at)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_FAILED,
        )

        self.assertIsNotNone(self.payout.completed_at)
        self.assertIsNotNone(self.payout.gateway_verified_at)

        self.assertEqual(
            self.payout.fsp_reference_id,
            "FSP-FAILED-001",
        )

        mock_token.assert_called_once()
        mock_query.assert_called_once()


