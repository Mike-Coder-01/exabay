
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from users.models import SellerProfile

from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
    SellerPayoutResolution,
    SellerPayoutFinalization,
)

from control_panel.services.payout_finalization import (
    finalize_manual_payout,
)


User = get_user_model()


class ManualPayoutFinalizationTests(TestCase):

    def setUp(self):
        self.admin_a = User.objects.create_superuser(
            username="finalization_admin_a",
            email="admin_a@example.com",
            password="TestPassword123!",
        )

        self.admin_b = User.objects.create_superuser(
            username="finalization_admin_b",
            email="admin_b@example.com",
            password="TestPassword123!",
        )

        self.normal_user = User.objects.create_user(
            username="finalization_normal",
            email="normal@example.com",
            password="TestPassword123!",
        )

        seller_user = User.objects.create_user(
            username="finalization_seller",
            email="seller@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=seller_user,
            business_name="Exxabay Test Seller",
            is_verified=True,
        )

        self.payout = SellerPayout.objects.create(
            seller=self.seller,
            created_by=self.admin_a,
            gross_amount="55000.00",
            commission_rate="10.00",
            commission_amount="5000.00",
            amount="50000.00",
            currency="TZS",
            phone_number="255712345678",
            account_name="Exxabay Test Seller",
            order_reference="EXX-FINALIZATION-001",
            status=SellerPayout.STATUS_PENDING,
        )

        self.investigation = (
            SellerPayoutInvestigation.objects.create(
                payout=self.payout,
                investigated_by=self.admin_a,
                reason="Gateway response unavailable",
                provider_reference="AZAM-MANUAL-001",
                findings="AzamPay independently confirmed payment.",
                outcome=(
                    SellerPayoutInvestigation.OUTCOME_CONFIRMED_PAID
                ),
            )
        )

        self.resolution = SellerPayoutResolution.objects.create(
            payout=self.payout,
            investigation=self.investigation,
            requested_by=self.admin_a,
            proposed_outcome=SellerPayoutResolution.OUTCOME_PAID,
            provider_reference="AZAM-MANUAL-001",
            evidence="Provider support confirmation recorded.",
        )

        # Simulate a completed two-administrator approval.
        # Approval itself must not finalize the payout.
        from django.utils import timezone

        SellerPayoutResolution.objects.filter(
            pk=self.resolution.pk
        ).update(
            status=SellerPayoutResolution.STATUS_APPROVED,
            approved_by=self.admin_b,
            approval_notes="Evidence independently reviewed.",
            decided_at=timezone.now(),
        )

        self.resolution.refresh_from_db()

    def finalize(self, **overrides):
        arguments = {
            "resolution_id": self.resolution.pk,
            "finalized_by": self.admin_b,
            "verification_method": "AzamPay support confirmation",
            "verification_evidence": (
                "Verified with AzamPay support. "
                "Transaction completed successfully."
            ),
            "provider_reference": "AZAM-MANUAL-001",
            "provider_confirmed": True,
        }

        arguments.update(overrides)

        return finalize_manual_payout(**arguments)

    def test_approved_resolution_can_be_finalized(self):
        result = self.finalize()

        self.assertTrue(result["success"])

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )

        self.assertIsNotNone(self.payout.completed_at)

        self.assertTrue(
            SellerPayoutFinalization.objects.filter(
                payout=self.payout,
                resolution=self.resolution,
            ).exists()
        )

    def test_unapproved_resolution_cannot_be_finalized(self):
        SellerPayoutResolution.objects.filter(
            pk=self.resolution.pk
        ).update(
            status=SellerPayoutResolution.STATUS_PENDING,
            approved_by=None,
            approval_notes="",
            decided_at=None,
        )

        result = self.finalize()

        self.assertFalse(result["success"])

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )

    def test_requester_cannot_finalize(self):
        result = self.finalize(
            finalized_by=self.admin_a,
        )

        self.assertFalse(result["success"])

        self.assertFalse(
            SellerPayoutFinalization.objects.filter(
                payout=self.payout
            ).exists()
        )

    def test_normal_user_cannot_finalize(self):
        result = self.finalize(
            finalized_by=self.normal_user,
        )

        self.assertFalse(result["success"])

    def test_duplicate_finalization_is_blocked(self):
        first_result = self.finalize()
        second_result = self.finalize()

        self.assertTrue(first_result["success"])
        self.assertFalse(second_result["success"])

        self.assertEqual(
            SellerPayoutFinalization.objects.filter(
                payout=self.payout
            ).count(),
            1,
        )

    def test_provider_confirmation_is_required(self):
        result = self.finalize(
            provider_confirmed=False,
        )

        self.assertFalse(result["success"])

        self.assertEqual(
            SellerPayoutFinalization.objects.count(),
            0,
        )

    def test_provider_reference_must_match(self):
        result = self.finalize(
            provider_reference="WRONG-REFERENCE",
        )

        self.assertFalse(result["success"])

    def test_completed_payout_cannot_be_finalized(self):
        self.payout.status = SellerPayout.STATUS_SUCCESS
        self.payout.save(update_fields=["status"])

        result = self.finalize()

        self.assertFalse(result["success"])

        self.assertEqual(
            SellerPayoutFinalization.objects.count(),
            0,
        )

    def test_finalization_does_not_delete_reservations(self):
        before = self.payout.reservations.count()

        result = self.finalize()

        after = self.payout.reservations.count()

        self.assertTrue(result["success"])
        self.assertEqual(before, after)

    @patch(
        "control_panel.services.azampay_payouts."
        "create_mobile_money_payout"
    )
    def test_finalization_does_not_send_money(self, mock_transfer):
        result = self.finalize()

        self.assertTrue(result["success"])
        mock_transfer.assert_not_called()

    def test_rejected_resolution_cannot_be_finalized(self):
        SellerPayoutResolution.objects.filter(
            pk=self.resolution.pk
        ).update(
            status=SellerPayoutResolution.STATUS_REJECTED,
        )

        result = self.finalize()

        self.assertFalse(result["success"])

    def test_investigation_outcome_must_match(self):
        SellerPayoutInvestigation.objects.filter(
            pk=self.investigation.pk
        ).update(
            outcome=SellerPayoutInvestigation.OUTCOME_CONFIRMED_FAILED,
        )

        result = self.finalize()

        self.assertFalse(result["success"])

    def test_missing_verification_evidence_is_blocked(self):
        result = self.finalize(
            verification_evidence="",
        )

        self.assertFalse(result["success"])

    def test_finalization_does_not_modify_resolution(self):
        original_status = self.resolution.status
        original_approver = self.resolution.approved_by_id

        result = self.finalize()

        self.resolution.refresh_from_db()

        self.assertTrue(result["success"])

        self.assertEqual(
            self.resolution.status,
            original_status,
        )

        self.assertEqual(
            self.resolution.approved_by_id,
            original_approver,
        )
