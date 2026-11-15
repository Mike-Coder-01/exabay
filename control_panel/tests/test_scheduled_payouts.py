
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from control_panel.management.commands.process_automatic_payouts import (
    Command,
)
from control_panel.models import SellerPayout, SellerPayoutAttempt
from control_panel.services.automatic_payouts import (
    prepare_automatic_payout,
)
from control_panel.tests.test_automatic_payouts import (
    AutomaticPayoutTests,
)


COMMAND_PATH = (
    "control_panel.management.commands.process_automatic_payouts"
)


class ScheduledPayoutTests(TestCase):

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=False
    )
    @patch(
        f"{COMMAND_PATH}.Command.process_scheduled_submissions"
    )
    @patch(
        f"{COMMAND_PATH}.Command.prepare_eligible_payouts"
    )
    def test_disabled_scheduler_does_not_submit(
        self,
        mock_prepare,
        mock_submit,
    ):
        call_command("process_automatic_payouts")

        mock_prepare.assert_called_once()
        mock_submit.assert_not_called()

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=True,
        AZAMPAY_AUTOMATIC_DISBURSEMENTS_ENABLED=True,
    )
    @patch(
        f"{COMMAND_PATH}.Command.process_scheduled_submissions"
    )
    @patch(
        f"{COMMAND_PATH}.Command.prepare_eligible_payouts"
    )
    def test_enabled_scheduler_invokes_submission(
        self,
        mock_prepare,
        mock_submit,
    ):
        call_command("process_automatic_payouts")

        mock_prepare.assert_called_once()
        mock_submit.assert_called_once()

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=True
    )
    @patch(
        f"{COMMAND_PATH}.claim_payout_for_initiation"
    )
    @patch(
        f"{COMMAND_PATH}.submit_claimed_payout"
    )
    def test_scheduler_with_no_eligible_payouts(
        self,
        mock_submit,
        mock_claim,
    ):
        command = Command()
        command.process_scheduled_submissions()

        mock_claim.assert_not_called()
        mock_submit.assert_not_called()

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=True
    )
    @patch(
        f"{COMMAND_PATH}.claim_payout_for_initiation"
    )
    @patch(
        f"{COMMAND_PATH}.submit_claimed_payout"
    )
    @patch(
        f"{COMMAND_PATH}.SellerPayout.objects"
    )
    def test_scheduler_excludes_existing_attempts(
        self,
        mock_objects,
        mock_submit,
        mock_claim,
    ):
        command = Command()

        command.process_scheduled_submissions()

        mock_objects.filter.assert_called_once_with(
            is_automatic=True,
            status=SellerPayout.STATUS_PENDING,
            pg_reference_id__isnull=True,
            initiated_at__isnull=True,
        )

        mock_objects.filter.return_value.exclude.assert_called_once()

        mock_claim.assert_not_called()
        mock_submit.assert_not_called()


class ScheduledPayoutDatabaseTests(AutomaticPayoutTests):

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=True
    )
    @patch(
        f"{COMMAND_PATH}.submit_claimed_payout"
    )
    @patch(
        f"{COMMAND_PATH}.claim_payout_for_initiation"
    )
    def test_unknown_attempt_is_not_resubmitted(
        self,
        mock_claim,
        mock_submit,
    ):
        payout = prepare_automatic_payout(
            self.fulfillment.pk
        )

        self.assertIsNotNone(payout)
        self.assertTrue(payout.is_automatic)

        SellerPayoutAttempt.objects.create(
            payout=payout,
            status=SellerPayoutAttempt.STATUS_UNKNOWN,
            error_message="Manual reconciliation required.",
        )

        command = Command()
        command.process_scheduled_submissions()

        mock_claim.assert_not_called()
        mock_submit.assert_not_called()

        self.assertEqual(
            SellerPayoutAttempt.objects.filter(
                payout=payout
            ).count(),
            1,
        )

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=True
    )
    @patch(
        f"{COMMAND_PATH}.submit_claimed_payout"
    )
    @patch(
        f"{COMMAND_PATH}.claim_payout_for_initiation"
    )
    def test_new_automatic_payout_is_selected(
        self,
        mock_claim,
        mock_submit,
    ):
        payout = prepare_automatic_payout(
            self.fulfillment.pk
        )

        self.assertIsNotNone(payout)
        self.assertTrue(payout.is_automatic)

        mock_attempt = mock_claim.return_value
        mock_attempt.pk = 123

        mock_submit.return_value = True

        command = Command()
        command.process_scheduled_submissions()

        mock_claim.assert_called_once_with(payout.pk)
        mock_submit.assert_called_once_with(123)

    @override_settings(
        AZAMPAY_SCHEDULED_SUBMISSIONS_ENABLED=True
    )
    @patch(
        f"{COMMAND_PATH}.submit_claimed_payout"
    )
    @patch(
        f"{COMMAND_PATH}.claim_payout_for_initiation"
    )
    def test_manual_payout_is_not_selected(
        self,
        mock_claim,
        mock_submit,
    ):
        payout = prepare_automatic_payout(
            self.fulfillment.pk
        )

        self.assertIsNotNone(payout)

        # Simulate a payout created manually.
        payout.is_automatic = False
        payout.save(update_fields=["is_automatic"])

        command = Command()
        command.process_scheduled_submissions()

        mock_claim.assert_not_called()
        mock_submit.assert_not_called()
