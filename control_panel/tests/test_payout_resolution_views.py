
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from users.models import SellerProfile

from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
    SellerPayoutResolution,
)


User = get_user_model()


class PayoutResolutionViewTests(TestCase):

    def setUp(self):
        # Administrator A requests the resolution
        self.admin_a = User.objects.create_superuser(
            username="resolution_admin_a",
            email="admin_a@example.com",
            password="TestPassword123!",
        )

        # Administrator B reviews the resolution
        self.admin_b = User.objects.create_superuser(
            username="resolution_admin_b",
            email="admin_b@example.com",
            password="TestPassword123!",
        )

        # Ordinary user must not access the approval page
        self.normal_user = User.objects.create_user(
            username="resolution_normal_user",
            email="normal@example.com",
            password="TestPassword123!",
        )

        # Create the payout
        self.payout = self.create_test_payout()

        # Administrator A records an investigation
        self.investigation = (
            SellerPayoutInvestigation.objects.create(
                payout=self.payout,
                investigated_by=self.admin_a,
                reason="Gateway outcome unknown",
                findings="Provider confirmed payment",
                provider_reference="AZAM-TEST-001",
                outcome=(
                    SellerPayoutInvestigation
                    .OUTCOME_CONFIRMED_PAID
                ),
            )
        )

        # Administrator A requests resolution
        self.resolution = SellerPayoutResolution.objects.create(
            payout=self.payout,
            investigation=self.investigation,
            requested_by=self.admin_a,
            proposed_outcome=(
                SellerPayoutResolution.OUTCOME_PAID
            ),
            provider_reference="AZAM-TEST-001",
            evidence="Verified provider confirmation",
        )

        self.url = reverse(
            "control_panel:review_payout_resolution",
            args=[self.resolution.pk],
        )

    def create_test_payout(self):
        """
        Create a valid test payout without contacting AzamPay.
        """

        seller_user = User.objects.create_user(
            username="resolution_test_seller",
            email="seller@example.com",
            password="TestPassword123!",
        )

        seller = SellerProfile.objects.create(
            user=seller_user,
            business_name="Exxabay Test Seller",
            is_verified=True,
        )

        payout = SellerPayout.objects.create(
            seller=seller,
            created_by=self.admin_a,
            gross_amount="55000.00",
            commission_rate="10.00",
            commission_amount="5000.00",
            amount="50000.00",
            currency="TZS",
            phone_number="255712345678",
            account_name="Exxabay Test Seller",
            order_reference="EXX-RESOLUTION-TEST-001",
            status=SellerPayout.STATUS_PENDING,
        )

        return payout

    def approval_payload(self):
        return {
            "decision": SellerPayoutResolution.STATUS_APPROVED,
            "approval_notes": (
                "Provider confirmation independently reviewed."
            ),
        }

    def test_superuser_can_open_review_page(self):
        self.client.force_login(self.admin_b)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Review payout resolution",
        )

    def test_normal_user_cannot_open_review_page(self):
        self.client.force_login(self.normal_user)

        response = self.client.get(self.url)

        self.assertNotEqual(response.status_code, 200)

    def test_requesting_admin_cannot_approve(self):
        self.client.force_login(self.admin_a)

        self.client.post(
            self.url,
            self.approval_payload(),
        )

        self.resolution.refresh_from_db()

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_PENDING,
        )

        self.assertIsNone(self.resolution.approved_by)

    def test_second_admin_can_approve(self):
        self.client.force_login(self.admin_b)

        response = self.client.post(
            self.url,
            self.approval_payload(),
        )

        self.resolution.refresh_from_db()

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_APPROVED,
        )

        self.assertEqual(
            self.resolution.approved_by,
            self.admin_b,
        )

        self.assertIsNotNone(
            self.resolution.decided_at,
        )

    def test_second_admin_can_reject(self):
        self.client.force_login(self.admin_b)

        response = self.client.post(
            self.url,
            {
                "decision": (
                    SellerPayoutResolution.STATUS_REJECTED
                ),
                "approval_notes": (
                    "Provider evidence is insufficient."
                ),
            },
        )

        self.resolution.refresh_from_db()

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_REJECTED,
        )

        self.assertEqual(
            self.resolution.approved_by,
            self.admin_b,
        )

    def test_duplicate_approval_is_blocked(self):
        self.client.force_login(self.admin_b)

        first_response = self.client.post(
            self.url,
            self.approval_payload(),
        )

        self.resolution.refresh_from_db()
        first_decided_at = self.resolution.decided_at

        second_response = self.client.post(
            self.url,
            self.approval_payload(),
        )

        self.resolution.refresh_from_db()

        self.assertEqual(first_response.status_code, 302)

        self.assertEqual(second_response.status_code, 200)

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_APPROVED,
        )

        self.assertEqual(
            self.resolution.decided_at,
            first_decided_at,
        )

    def test_approval_does_not_change_payout(self):
        original_status = self.payout.status

        self.client.force_login(self.admin_b)

        self.client.post(
            self.url,
            self.approval_payload(),
        )

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            original_status,
        )

    @patch(
        "control_panel.services.azampay_payouts."
        "create_mobile_money_payout"
    )
    def test_approval_does_not_send_money(self, mock_transfer):
        self.client.force_login(self.admin_b)

        self.client.post(
            self.url,
            self.approval_payload(),
        )

        self.resolution.refresh_from_db()

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_APPROVED,
        )

        mock_transfer.assert_not_called()

    def test_csrf_protection(self):
        client = Client(enforce_csrf_checks=True)

        client.force_login(self.admin_b)

        response = client.post(
            self.url,
            self.approval_payload(),
        )

        self.assertEqual(response.status_code, 403)

        self.resolution.refresh_from_db()

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_PENDING,
        )
