
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from control_panel.models import (
    SellerPayout,
    SellerPayoutAttempt,
)
from control_panel.services.payout_initiation import (
    record_payout_submission_result,
)
from control_panel.services.azampay_payout_callbacks import (
    verify_disbursement_callback,
)
from control_panel.tests.test_seller_payout_initiation import (
    SellerPayoutInitiationTests,
)
from control_panel.models import SellerPayout

class PayoutCallbackReconciliationTests(TestCase):

    def setUp(self):
        # Reuse the existing seller/order/payment fixture.
        SellerPayoutInitiationTests.setUp(self)

        self.payout.status = SellerPayout.STATUS_PENDING
        self.payout.save(update_fields=["status"])

        self.attempt = SellerPayoutAttempt.objects.create(
            payout=self.payout,
            status=SellerPayoutAttempt.STATUS_SUBMITTING,
            submitting_at=timezone.now(),
        )

        self.pg_reference = "PG-RECON-001"

    def gateway_response(self, reference=None):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "pgReferenceId": reference or self.pg_reference,
        }
        return response

    def callback_payload(self, reference=None):
        return {
            "initiatorReferenceId": self.payout.order_reference,
            "pgReferenceId": reference or self.pg_reference,
        }

    def verified_status_response(self, status="success"):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "success": True,
            "initiatorReferenceId": self.payout.order_reference,
            "pgReferenceId": self.pg_reference,
            "amount": "1000.00",
            "operator": self.payout.channel_provider,
            "status": status,
            "fspReferenceId": "FSP-RECON-001",
        }
        return response

    def finalize_callback(self, status="success"):
        with (
            patch(
                "control_panel.services."
                "azampay_payout_callbacks."
                "generate_disbursement_token",
                return_value="fake-token",
            ),
            patch(
                "control_panel.services."
                "azampay_payout_callbacks."
                "query_payout_status",
                return_value=self.verified_status_response(status),
            ),
        ):
            return verify_disbursement_callback(
                self.callback_payload()
            )

    def test_accepted_response_then_success_callback(self):
        recorded = record_payout_submission_result(
            self.attempt.pk,
            response=self.gateway_response(),
        )

        self.assertTrue(recorded)

        result = self.finalize_callback()

        self.payout.refresh_from_db()
        self.attempt.refresh_from_db()

        self.assertEqual(result, SellerPayout.STATUS_SUCCESS)
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )

    def test_success_callback_before_accepted_response(self):
        self.finalize_callback()

        recorded = record_payout_submission_result(
            self.attempt.pk,
            response=self.gateway_response(),
        )

        self.payout.refresh_from_db()
        self.attempt.refresh_from_db()

        self.assertTrue(recorded)
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )
        self.assertEqual(
            self.payout.pg_reference_id,
            self.pg_reference,
        )

    def test_success_callback_before_timeout(self):
        self.finalize_callback()

        recorded = record_payout_submission_result(
            self.attempt.pk,
            response=None,
        )

        self.payout.refresh_from_db()
        self.attempt.refresh_from_db()

        self.assertTrue(recorded)
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.attempt.status,
            SellerPayoutAttempt.STATUS_UNKNOWN,
        )
        self.assertEqual(
            self.payout.pg_reference_id,
            self.pg_reference,
        )

    def test_conflicting_gateway_reference(self):
        self.finalize_callback()

        recorded = record_payout_submission_result(
            self.attempt.pk,
            response=self.gateway_response(
                reference="PG-DIFFERENT-999"
            ),
        )

        self.payout.refresh_from_db()
        self.attempt.refresh_from_db()

        self.assertTrue(recorded)
        self.assertEqual(
            self.attempt.status,
            SellerPayoutAttempt.STATUS_UNKNOWN,
        )
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.payout.pg_reference_id,
            self.pg_reference,
        )

    def test_duplicate_success_callback_is_ignored(self):
        first_result = self.finalize_callback()
        self.payout.refresh_from_db()
        first_completed_at = self.payout.completed_at

        second_result = self.finalize_callback()
        self.payout.refresh_from_db()

        self.assertEqual(
            first_result,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(second_result, "ignored")
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.payout.completed_at,
            first_completed_at,
        )

    def test_unverified_callback_cannot_finalize_payout(self):
        invalid_response = self.verified_status_response()
        invalid_response.json.return_value["amount"] = "9999.00"

        with (
            patch(
                "control_panel.services."
                "azampay_payout_callbacks."
                "generate_disbursement_token",
                return_value="fake-token",
            ),
            patch(
                "control_panel.services."
                "azampay_payout_callbacks."
                "query_payout_status",
                return_value=invalid_response,
            ),
        ):
            with self.assertRaises(ValueError):
                verify_disbursement_callback(
                    self.callback_payload()
                )

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )
        self.assertIsNone(self.payout.completed_at)


    def test_callback_cannot_finalize_uninitiated_payout(self):
        """
        A payout that has never reached the submitting
        stage must not be finalized by a callback.
        """

        # Simulate a prepared payout with no transfer attempt.
        self.attempt.delete()

        with (
            patch(
                "control_panel.services."
                "azampay_payout_callbacks."
                "generate_disbursement_token",
                return_value="fake-token",
            ),
            patch(
                "control_panel.services."
                "azampay_payout_callbacks."
                "query_payout_status",
                return_value=self.verified_status_response(),
            ),
        ):
            result = verify_disbursement_callback(
                self.callback_payload()
            )

        self.payout.refresh_from_db()

        self.assertEqual(result, "ignored")
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )
        self.assertIsNone(self.payout.completed_at)
