
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from users.models import SellerProfile
from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
)


class PayoutInvestigationTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="investigation_admin",
            email="investigation-admin@example.com",
            password="TestPassword123!",
        )

        self.regular_user = User.objects.create_user(
            username="investigation_user",
            email="investigation-user@example.com",
            password="TestPassword123!",
        )

        self.seller_user = User.objects.create_user(
            username="investigation_seller",
            email="investigation-seller@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            business_name="Test Investigation Seller",
            is_verified=True,
        )

        self.payout = SellerPayout.objects.create(
            seller=self.seller,
            gross_amount=Decimal("55000.00"),
            commission_amount=Decimal("5000.00"),
            amount=Decimal("50000.00"),
            currency="TZS",
            phone_number="255700000000",
            account_name="Test Seller",
            channel_provider="Azampesa",
            order_reference="EXX-INV-001",
            status=SellerPayout.STATUS_PENDING,
        )

        self.url = reverse(
            "control_panel:investigate_seller_payout",
            args=[self.payout.pk],
        )

        self.valid_data = {
            "reason": "AzamPay initiation timed out.",
            "provider_reference": "",
            "findings": "Waiting for confirmation from AzamPay.",
            "outcome": SellerPayoutInvestigation.OUTCOME_UNKNOWN,
        }

    def test_superuser_can_create_investigation(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            self.valid_data,
        )

        self.assertRedirects(
            response,
            reverse("control_panel:seller_payouts"),
            fetch_redirect_response=False,
        )

        investigation = SellerPayoutInvestigation.objects.get()

        self.assertEqual(
            investigation.payout,
            self.payout,
        )
        self.assertEqual(
            investigation.investigated_by,
            self.admin,
        )
        self.assertEqual(
            investigation.outcome,
            SellerPayoutInvestigation.OUTCOME_UNKNOWN,
        )

    def test_regular_user_cannot_create_investigation(self):
        self.client.force_login(self.regular_user)

        response = self.client.post(
            self.url,
            self.valid_data,
        )

        self.assertIn(response.status_code, [302, 403])

        self.assertFalse(
            SellerPayoutInvestigation.objects.exists()
        )

    def test_confirmed_outcome_requires_evidence(self):
        self.client.force_login(self.admin)

        data = {
            "reason": "Checking payout status.",
            "provider_reference": "",
            "findings": "",
            "outcome": (
                SellerPayoutInvestigation.OUTCOME_CONFIRMED_PAID
            ),
        }

        response = self.client.post(self.url, data)

        self.assertEqual(response.status_code, 200)

        self.assertFalse(
            SellerPayoutInvestigation.objects.exists()
        )

        self.assertIn(
            "findings",
            response.context["form"].errors,
        )
        self.assertIn(
            "provider_reference",
            response.context["form"].errors,
        )

    @patch(
        "control_panel.services.azampay_payouts."
        "create_mobile_money_payout"
    )
    def test_investigation_does_not_send_money(
        self,
        mock_transfer,
    ):
        self.client.force_login(self.admin)

        response = self.client.post(
            self.url,
            self.valid_data,
        )

        self.assertEqual(response.status_code, 302)

        mock_transfer.assert_not_called()

    def test_investigation_does_not_change_payout_status(self):
        self.client.force_login(self.admin)

        original_status = self.payout.status

        self.client.post(
            self.url,
            self.valid_data,
        )

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            original_status,
        )

    def test_investigation_preserves_existing_reservations(self):
        self.client.force_login(self.admin)

        # Count existing reservations before investigation.
        before = self.payout.reservations.count()

        self.client.post(
            self.url,
            self.valid_data,
        )

        after = self.payout.reservations.count()

        self.assertEqual(before, after)

    def test_investigation_history_is_preserved(self):
        self.client.force_login(self.admin)

        self.client.post(
            self.url,
            self.valid_data,
        )

        self.client.post(
            self.url,
            {
                "reason": "Follow-up with AzamPay.",
                "provider_reference": "PG-INV-001",
                "findings": "AzamPay is still investigating.",
                "outcome": (
                    SellerPayoutInvestigation.OUTCOME_UNKNOWN
                ),
            },
        )

        self.assertEqual(
            SellerPayoutInvestigation.objects.filter(
                payout=self.payout
            ).count(),
            2,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["investigations"].count(),
            2,
        )

    def test_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.post(
            self.url,
            self.valid_data,
        )

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            SellerPayoutInvestigation.objects.exists()
        )
