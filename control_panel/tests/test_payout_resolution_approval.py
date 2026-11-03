
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from users.models import SellerProfile
from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
    SellerPayoutResolution,
)
from control_panel.services.payout_resolution_approval import (
    decide_payout_resolution,
)


class PayoutResolutionApprovalTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.requester = User.objects.create_superuser(
            username="resolution_requester",
            email="requester@example.com",
            password="TestPassword123!",
        )

        self.approver = User.objects.create_superuser(
            username="resolution_approver",
            email="approver@example.com",
            password="TestPassword123!",
        )

        self.regular_user = User.objects.create_user(
            username="resolution_regular",
            email="regular@example.com",
            password="TestPassword123!",
        )

        seller_user = User.objects.create_user(
            username="approval_test_seller",
            email="seller@example.com",
            password="TestPassword123!",
        )

        seller = SellerProfile.objects.create(
            user=seller_user,
            business_name="Approval Test Seller",
            is_verified=True,
        )

        self.payout = SellerPayout.objects.create(
            seller=seller,
            gross_amount=Decimal("55000.00"),
            commission_amount=Decimal("5000.00"),
            amount=Decimal("50000.00"),
            currency="TZS",
            phone_number="255700000000",
            account_name="Approval Test Seller",
            channel_provider="Azampesa",
            order_reference="EXX-APPROVAL-001",
            status=SellerPayout.STATUS_PENDING,
        )

        self.investigation = SellerPayoutInvestigation.objects.create(
            payout=self.payout,
            investigated_by=self.requester,
            reason="AzamPay response timeout.",
            provider_reference="AZAM-CASE-001",
            findings="Provider reported payment completed.",
            outcome=SellerPayoutInvestigation.OUTCOME_CONFIRMED_PAID,
        )

        self.resolution = SellerPayoutResolution.objects.create(
            payout=self.payout,
            investigation=self.investigation,
            requested_by=self.requester,
            proposed_outcome=SellerPayoutResolution.OUTCOME_PAID,
            provider_reference="AZAM-CASE-001",
            evidence="Written confirmation from AzamPay support.",
        )

    def decide(self, **overrides):
        data = {
            "resolution_id": self.resolution.pk,
            "decided_by": self.approver,
            "decision": SellerPayoutResolution.STATUS_APPROVED,
            "approval_notes": "Provider evidence reviewed.",
        }

        data.update(overrides)

        return decide_payout_resolution(**data)

    def test_different_superuser_can_approve(self):
        result = self.decide()

        self.assertTrue(result["success"])

        self.resolution.refresh_from_db()

        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_APPROVED,
        )
        self.assertEqual(
            self.resolution.approved_by,
            self.approver,
        )
        self.assertIsNotNone(self.resolution.decided_at)

    def test_requester_cannot_approve_own_request(self):
        result = self.decide(decided_by=self.requester)

        self.assertFalse(result["success"])

        self.resolution.refresh_from_db()
        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_PENDING,
        )

    def test_regular_user_cannot_approve(self):
        result = self.decide(decided_by=self.regular_user)

        self.assertFalse(result["success"])

        self.resolution.refresh_from_db()
        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_PENDING,
        )

    def test_superuser_can_reject(self):
        result = self.decide(
            decision=SellerPayoutResolution.STATUS_REJECTED,
            approval_notes="Evidence insufficient.",
        )

        self.assertTrue(result["success"])

        self.resolution.refresh_from_db()
        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_REJECTED,
        )

    def test_duplicate_approval_is_rejected(self):
        first = self.decide()
        second = self.decide()

        self.assertTrue(first["success"])
        self.assertFalse(second["success"])

    def test_decision_cannot_be_reversed(self):
        self.decide()

        result = self.decide(
            decision=SellerPayoutResolution.STATUS_REJECTED,
        )

        self.assertFalse(result["success"])

        self.resolution.refresh_from_db()
        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_APPROVED,
        )

    def test_approval_does_not_change_payout_status(self):
        original_status = self.payout.status

        result = self.decide()

        self.assertTrue(result["success"])

        self.payout.refresh_from_db()
        self.assertEqual(self.payout.status, original_status)

    def test_missing_approval_notes_is_rejected(self):
        result = self.decide(approval_notes="")

        self.assertFalse(result["success"])

        self.resolution.refresh_from_db()
        self.assertEqual(
            self.resolution.status,
            SellerPayoutResolution.STATUS_PENDING,
        )

    def test_completed_payout_cannot_be_approved(self):
        self.payout.status = SellerPayout.STATUS_SUCCESS
        self.payout.save(update_fields=["status"])

        result = self.decide()

        self.assertFalse(result["success"])

    def test_investigation_mismatch_is_rejected(self):
        self.investigation.outcome = (
            SellerPayoutInvestigation.OUTCOME_CONFIRMED_FAILED
        )
        self.investigation.save(update_fields=["outcome"])

        result = self.decide()

        self.assertFalse(result["success"])
