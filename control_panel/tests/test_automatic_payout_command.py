
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.utils import timezone

from control_panel.models import (
    SellerPayout,
    SellerPayoutReservation,
)
from control_panel.tests.test_automatic_payouts import (
    AutomaticPayoutTests,
)


COMMAND_MODULE = (
    "control_panel.management.commands."
    "process_automatic_payouts"
)


class AutomaticPayoutCommandTests(AutomaticPayoutTests):
    """
    Tests the management command using the existing
    seller, buyer, order, payment, and fulfillment fixtures.
    """

    def run_command(self):
        output = StringIO()

        call_command(
            "process_automatic_payouts",
            stdout=output,
        )

        return output.getvalue()

    def set_fulfillment_times(
        self,
        shipped_hours_ago,
        release_hours_from_now,
        buyer_confirmed=False,
    ):
        now = timezone.now()

        self.fulfillment.shipped_at = (
            now - timedelta(hours=shipped_hours_ago)
        )

        self.fulfillment.release_at = (
            now + timedelta(hours=release_hours_from_now)
        )

        self.fulfillment.buyer_confirmed_at = (
            now if buyer_confirmed else None
        )

        self.fulfillment.save(
            update_fields=[
                "shipped_at",
                "release_at",
                "buyer_confirmed_at",
            ]
        )

    @patch(
        COMMAND_MODULE + ".prepare_automatic_payout"
    )
    def test_processes_fulfillment_after_60_hours(
        self,
        mocked_prepare,
    ):
        self.set_fulfillment_times(
            shipped_hours_ago=61,
            release_hours_from_now=-1,
        )

        self.run_command()

        mocked_prepare.assert_called_once_with(
            self.fulfillment.pk
        )

    @patch(
        COMMAND_MODULE + ".prepare_automatic_payout"
    )
    def test_processes_early_buyer_confirmation(
        self,
        mocked_prepare,
    ):
        self.set_fulfillment_times(
            shipped_hours_ago=1,
            release_hours_from_now=59,
            buyer_confirmed=True,
        )

        self.run_command()

        mocked_prepare.assert_called_once_with(
            self.fulfillment.pk
        )

    @patch(
        COMMAND_MODULE + ".prepare_automatic_payout"
    )
    def test_skips_before_60_hours(
        self,
        mocked_prepare,
    ):
        self.set_fulfillment_times(
            shipped_hours_ago=1,
            release_hours_from_now=59,
        )

        self.run_command()

        mocked_prepare.assert_not_called()

    @patch(
        COMMAND_MODULE + ".prepare_automatic_payout"
    )
    def test_skips_unpaid_orders(
        self,
        mocked_prepare,
    ):
        self.payment.status = "pending"
        self.payment.save(
            update_fields=["status"]
        )

        self.run_command()

        mocked_prepare.assert_not_called()

    @patch(
        COMMAND_MODULE + ".prepare_automatic_payout"
    )
    def test_command_handles_preparation_failure(
        self,
        mocked_prepare,
    ):
        mocked_prepare.side_effect = RuntimeError(
            "Simulated payout preparation failure"
        )

        output = self.run_command()

        mocked_prepare.assert_called_once_with(
            self.fulfillment.pk
        )

        self.assertIn(
            "Failed: 1",
            output,
        )

    def test_command_creates_real_payout(self):
        """
        Integration test:
        Use the actual preparation service without mocks.
        """

        output = self.run_command()

        self.assertEqual(
            SellerPayout.objects.count(),
            1,
        )

        payout = SellerPayout.objects.get()

        self.assertEqual(
            payout.amount,
            Decimal("1000.00"),
        )

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

        self.assertTrue(
            SellerPayoutReservation.objects.filter(
                payout=payout,
                order_item=self.item,
            ).exists()
        )

        self.assertIn(
            "Prepared: 1",
            output,
        )

    def test_running_command_twice_prevents_duplicates(self):
        """
        The same order item must not receive
        multiple automatic payout reservations.
        """

        self.run_command()
        self.run_command()

        self.assertEqual(
            SellerPayout.objects.count(),
            1,
        )

        self.assertEqual(
            SellerPayoutReservation.objects.count(),
            1,
        )
