
from unittest.mock import Mock, patch

from django.test import override_settings

from control_panel.models import (
    SellerPayout,
    SellerPayoutAttempt,
    SellerPayoutReservation,
)
from control_panel.services.automatic_payouts import (
    prepare_automatic_payout,
)
from control_panel.services.payout_initiation import (
    claim_payout_for_initiation,
    mark_payout_submitting,
    record_payout_submission_result,
    submit_claimed_payout,
)
from control_panel.tests.test_automatic_payouts import (
    AutomaticPayoutTests,
)
from orders.models import SellerFulfillment


class PayoutInitiationTests(AutomaticPayoutTests):
    """
    Test payout claiming, submission states, and
    duplicate-transfer prevention.

    Reuses fixtures from AutomaticPayoutTests.
    """

    def create_claimed_payout(self):
        """Prepare and claim an eligible seller payout."""
        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.assertIsNotNone(payout)

        attempt = claim_payout_for_initiation(payout.pk)

        self.assertIsNotNone(attempt)

        return payout, attempt

    # ---------------------------------------------------------
    # 1. PAYOUT CLAIMING
    # ---------------------------------------------------------

    def test_eligible_payout_can_be_claimed(self):
        payout, attempt = self.create_claimed_payout()

        self.assertEqual(attempt.payout_id, payout.pk)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_CLAIMED,
        )
        self.assertEqual(
            SellerPayoutAttempt.objects.count(),
            1,
        )

    def test_same_payout_cannot_be_claimed_twice(self):
        payout, first = self.create_claimed_payout()

        second = claim_payout_for_initiation(payout.pk)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            SellerPayoutAttempt.objects.count(),
            1,
        )

    def test_payout_without_reservation_is_rejected(self):
        payout = prepare_automatic_payout(self.fulfillment.pk)

        SellerPayoutReservation.objects.filter(
            payout=payout,
        ).delete()

        attempt = claim_payout_for_initiation(payout.pk)

        self.assertIsNone(attempt)
        self.assertFalse(
            SellerPayoutAttempt.objects.filter(
                payout=payout,
            ).exists()
        )

    def test_ineligible_fulfillment_is_rejected(self):
        payout = prepare_automatic_payout(self.fulfillment.pk)

        self.fulfillment.dispute_status = (
            SellerFulfillment.DISPUTE_OPEN
        )
        self.fulfillment.save(
            update_fields=["dispute_status"]
        )

        attempt = claim_payout_for_initiation(payout.pk)

        self.assertIsNone(attempt)
        self.assertEqual(
            SellerPayoutAttempt.objects.count(),
            0,
        )

    def test_existing_attempt_blocks_new_claim(self):
        payout = prepare_automatic_payout(self.fulfillment.pk)

        SellerPayoutAttempt.objects.create(
            payout=payout,
            status=SellerPayoutAttempt.STATUS_UNKNOWN,
        )

        attempt = claim_payout_for_initiation(payout.pk)

        self.assertIsNone(attempt)
        self.assertEqual(
            SellerPayoutAttempt.objects.count(),
            1,
        )

    @patch(
        "control_panel.services.azampay_payouts."
        "create_mobile_money_payout"
    )
    def test_claim_does_not_send_money(self, mock_transfer):
        self.create_claimed_payout()

        mock_transfer.assert_not_called()

    # ---------------------------------------------------------
    # 2. SUBMISSION STATE TRANSITIONS
    # ---------------------------------------------------------

    def test_claimed_payout_can_be_marked_submitting(self):
        _, attempt = self.create_claimed_payout()

        result = mark_payout_submitting(attempt.pk)

        attempt.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_SUBMITTING,
        )
        self.assertIsNotNone(attempt.submitting_at)

    def test_submitting_payout_cannot_be_marked_again(self):
        _, attempt = self.create_claimed_payout()

        first = mark_payout_submitting(attempt.pk)
        second = mark_payout_submitting(attempt.pk)

        self.assertTrue(first)
        self.assertFalse(second)

    # ---------------------------------------------------------
    # 3. AZAMPAY SUBMISSION RESULTS
    # ---------------------------------------------------------

    def test_accepted_submission_records_gateway_reference(self):
        payout, attempt = self.create_claimed_payout()

        self.assertTrue(mark_payout_submitting(attempt.pk))

        response = Mock(status_code=200)
        response.json.return_value = {
            "success": True,
            "pgReferenceId": "PG-AUTO-001",
            "status": "processing",
        }

        result = record_payout_submission_result(
            attempt.pk,
            response=response,
        )

        payout.refresh_from_db()
        attempt.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )
        self.assertEqual(
            payout.pg_reference_id,
            "PG-AUTO-001",
        )
        self.assertEqual(
            payout.status,
            SellerPayout.STATUS_PROCESSING,
        )

    def test_timeout_records_unknown_outcome(self):
        payout, attempt = self.create_claimed_payout()

        self.assertTrue(mark_payout_submitting(attempt.pk))

        result = record_payout_submission_result(
            attempt.pk,
            response=None,
        )

        payout.refresh_from_db()
        attempt.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_UNKNOWN,
        )
        self.assertEqual(
            payout.status,
            SellerPayout.STATUS_PENDING,
        )

    def test_submission_result_cannot_be_recorded_twice(self):
        _, attempt = self.create_claimed_payout()

        self.assertTrue(mark_payout_submitting(attempt.pk))

        first = record_payout_submission_result(
            attempt.pk,
            response=None,
        )
        second = record_payout_submission_result(
            attempt.pk,
            response=None,
        )

        self.assertTrue(first)
        self.assertFalse(second)

    # ---------------------------------------------------------
    # 4. AUTOMATIC DISBURSEMENT FEATURE FLAG
    # ---------------------------------------------------------

    @override_settings(
        AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED=False
    )
    @patch(
        "control_panel.services.payout_initiation."
        "create_mobile_money_payout"
    )
    def test_disabled_feature_cannot_submit(self, mock_transfer):
        _, attempt = self.create_claimed_payout()

        result = submit_claimed_payout(attempt.pk)

        attempt.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_CLAIMED,
        )
        mock_transfer.assert_not_called()

    
    @override_settings(
        AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED=True,
        AZAMPAY_DISBURSEMENT_SOURCE={
            "countryCode": "TZ",
            "fullName": "Exxabay Test Wallet",
            "bankName": "Azampesa",
            "accountNumber": "TEST-WALLET-001",
            "currency": "TZS",
        },
        AZAMPAY_DISBURSEMENT_PUBLIC_KEY="TEST-PUBLIC-KEY",
    )
    @patch(
        "control_panel.services.payout_initiation."
        "create_mobile_money_payout"
    )
    @patch(
        "control_panel.services.payout_initiation."
        "generate_disbursement_checksum"
    )
    @patch(
        "control_panel.services.payout_initiation."
        "generate_disbursement_token"
    )
    def test_successful_automatic_submission(
        self,
        mock_token,
        mock_checksum,
        mock_transfer,
    ):
        payout, attempt = self.create_claimed_payout()

        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        response = Mock(status_code=200)
        response.json.return_value = {
            "success": True,
            "pgReferenceId": "PG-AUTO-SUBMIT-001",
            "status": "processing",
        }
        mock_transfer.return_value = response

        result = submit_claimed_payout(attempt.pk)

        payout.refresh_from_db()
        attempt.refresh_from_db()

        self.assertTrue(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )
        self.assertEqual(
            payout.status,
            SellerPayout.STATUS_PROCESSING,
        )
        self.assertEqual(
            payout.pg_reference_id,
            "PG-AUTO-SUBMIT-001",
        )

        mock_transfer.assert_called_once()

        self.assertEqual(
            mock_transfer.call_args.kwargs["amount"],
            payout.amount,
        )
        self.assertEqual(
            mock_transfer.call_args.kwargs["order_reference"],
            payout.order_reference,
        )
        self.assertEqual(
            mock_transfer.call_args.kwargs["phone_number"],
            payout.phone_number,
        )


    
    @override_settings(
        AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED=True
    )
    @patch(
        "control_panel.services.payout_initiation."
        "create_mobile_money_payout"
    )
    @patch(
        "control_panel.services.payout_initiation."
        "generate_disbursement_checksum"
    )
    @patch(
        "control_panel.services.payout_initiation."
        "generate_disbursement_token"
    )
    def test_submission_timeout_does_not_retry(
        self,
        mock_token,
        mock_checksum,
        mock_transfer,
    ):
        payout, attempt = self.create_claimed_payout()

        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"
        mock_transfer.return_value = None

        first = submit_claimed_payout(attempt.pk)
        second = submit_claimed_payout(attempt.pk)

        attempt.refresh_from_db()
        payout.refresh_from_db()

        self.assertTrue(first)
        self.assertFalse(second)

        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_UNKNOWN,
        )
        self.assertEqual(
            payout.status,
            SellerPayout.STATUS_PENDING,
        )

        mock_transfer.assert_called_once()


    @override_settings(
        AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED=True
    )
    @patch(
        "control_panel.services.payout_initiation."
        "create_mobile_money_payout"
    )
    @patch(
        "control_panel.services.payout_initiation."
        "generate_disbursement_token"
    )
    def test_authentication_failure_does_not_submit(
        self,
        mock_token,
        mock_transfer,
    ):
        _, attempt = self.create_claimed_payout()

        mock_token.return_value = None

        result = submit_claimed_payout(attempt.pk)

        attempt.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_CLAIMED,
        )

        mock_transfer.assert_not_called()


    def test_dispute_opened_after_claim_blocks_submission(self):
        payout, attempt = self.create_claimed_payout()

        # Buyer opens a dispute after the payout was claimed.
        self.fulfillment.dispute_status = (
            SellerFulfillment.DISPUTE_OPEN
        )
        self.fulfillment.save(
            update_fields=["dispute_status"]
        )

        result = mark_payout_submitting(attempt.pk)

        attempt.refresh_from_db()
        payout.refresh_from_db()

        self.assertFalse(result)
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_CLAIMED,
        )
        self.assertEqual(
            payout.status,
            SellerPayout.STATUS_PENDING,
        )

