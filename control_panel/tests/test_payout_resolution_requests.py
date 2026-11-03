
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from users.models import SellerProfile
from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
    SellerPayoutResolution,
)
from control_panel.services.payout_resolution_requests import (
    request_payout_resolution,
)


class PayoutResolutionRequestTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="resolution_request_admin",
            email="request-admin@example.com",
            password="TestPassword123!",
        )

        self.regular_user = User.objects.create_user(
            username="resolution_request_user",
            email="request-user@example.com",
            password="TestPassword123!",
        )

        seller_user = User.objects.create_user(
            username="resolution_request_seller",
            email="request-seller@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=seller_user,
            business_name="Test Seller",
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
            order_reference="EXX-REQUEST-001",
            status=SellerPayout.STATUS_PENDING,
        )

        self.investigation = SellerPayoutInvestigation.objects.create(
            payout=self.payout,
            investigated_by=self.admin,
            reason="AzamPay response timeout.",
            provider_reference="AZAM-CASE-001",
            findings="Provider confirmed transaction completed.",
            outcome=SellerPayoutInvestigation.OUTCOME_CONFIRMED_PAID,
        )

    def request_resolution(self, **overrides):
        data = {
            "payout_id": self.payout.pk,
            "investigation_id": self.investigation.pk,
            "requested_by": self.admin,
            "proposed_outcome": SellerPayoutResolution.OUTCOME_PAID,
            "provider_reference": "AZAM-CASE-001",
            "evidence": "Written confirmation from AzamPay support.",
        }

        data.update(overrides)

        return request_payout_resolution(**data)

    def test_superuser_can_request_resolution(self):
        result = self.request_resolution()

        self.assertTrue(result["success"])

        resolution = SellerPayoutResolution.objects.get()

        self.assertEqual(
            resolution.status,
            SellerPayoutResolution.STATUS_PENDING,
        )
        self.assertEqual(resolution.requested_by, self.admin)

    def test_regular_user_cannot_request_resolution(self):
        result = self.request_resolution(
            requested_by=self.regular_user
        )

        self.assertFalse(result["success"])
        self.assertFalse(
            SellerPayoutResolution.objects.exists()
        )

    def test_duplicate_pending_request_is_rejected(self):
        first = self.request_resolution()
        second = self.request_resolution()

        self.assertTrue(first["success"])
        self.assertFalse(second["success"])

        self.assertEqual(
            SellerPayoutResolution.objects.count(),
            1,
        )

    def test_mismatched_outcome_is_rejected(self):
        result = self.request_resolution(
            proposed_outcome=SellerPayoutResolution.OUTCOME_FAILED
        )

        self.assertFalse(result["success"])

    def test_request_does_not_change_payout_status(self):
        original_status = self.payout.status

        result = self.request_resolution()

        self.assertTrue(result["success"])

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            original_status,
        )
