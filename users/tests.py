from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from .models import User, SellerProfile, SellerSettings
from .views import get_payout_account_state

# Create your tests here.
class UserModelTest(TestCase):

    def test_create_user(self):
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='pass1234'
        )
        self.assertEqual(user.email, 'test@example.com')
        self.assertFalse(user.is_seller)


# Test SellerProfile Auto Creation
class SellerProfileTest(TestCase):

    def test_seller_profile_created_when_user_is_seller(self):
        user = User.objects.create_user(
            username='seller',
            email='seller@test.com',
            password='pass1234',
            is_seller=True
        )
        self.assertTrue(SellerProfile.objects.filter(user=user).exists())


    def test_no_profile_for_non_seller(self):
        user = User.objects.create_user(
            username='buyer',
            email='buyer@test.com',
            password='pass1234',
            is_seller=False
        )
        self.assertFalse(SellerProfile.objects.filter(user=user).exists())


    def test_profile_incomplete(self):
        user = User.objects.create_user(
            username='seller2',
            email='seller2@test.com',
            password='pass1234',
            is_seller=True
        )

        profile = user.sellerprofile
        self.assertFalse(profile.is_profile_complete())



class SellerPayoutVerificationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="payoutseller",
            email="payoutseller@example.com",
            password="TestPassword123!",
            is_seller=True,
        )

        self.seller = SellerProfile.objects.get(
            user=self.user
        )

        self.settings, _ = SellerSettings.objects.get_or_create(
            seller=self.seller
        )

        self.client.force_login(self.user)

    def test_confirm_verified_payout_account(self):
        """
        A seller can confirm an account that has
        already passed simulated NameLookup.
        """

        session = self.client.session

        session["pending_payout_verification"] = {
            "seller_id": self.seller.pk,
            "provider": "mpesa",
            "phone_number": "0712345678",
            "account_name": "John Doe",
            "verified_at": timezone.now().isoformat(),
            "original_account_state": get_payout_account_state(self.settings),
        }

        session.save()

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.mobile_money_provider,
            "mpesa",
        )

        self.assertEqual(
            self.settings.payout_phone_number,
            "0712345678",
        )

        self.assertEqual(
            self.settings.payout_account_name,
            "John Doe",
        )

        self.assertTrue(
            self.settings.payout_account_verified
        )

        self.assertIsNotNone(
            self.settings.payout_verified_at
        )

    
    def test_expired_payout_verification_is_rejected(self):
        """
        An expired NameLookup result must not
        update the seller's payout account.
        """

        # Existing verified account
        self.settings.mobile_money_provider = "mpesa"
        self.settings.payout_phone_number = "0711111111"
        self.settings.payout_account_name = "Existing Seller"
        self.settings.payout_account_verified = True
        self.settings.payout_verified_at = timezone.now()
        self.settings.save()

        # Simulate verification completed 15 minutes ago.
        session = self.client.session

        session["pending_payout_verification"] = {
            "seller_id": self.seller.pk,
            "provider": "mpesa",
            "phone_number": "0722222222",
            "account_name": "New Seller",
            "verified_at": (
                timezone.now() - timedelta(minutes=15)
            ).isoformat(),
            "original_account_state": get_payout_account_state(self.settings),
        }

        session.save()

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        # The old verified account must remain unchanged.
        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )

        self.assertEqual(
            self.settings.payout_account_name,
            "Existing Seller",
        )

        self.assertTrue(
            self.settings.payout_account_verified
        )

        # Expired verification must be removed.
        self.assertNotIn(
            "pending_payout_verification",
            self.client.session,
        )

    
    def set_existing_verified_account(self):
        """Create an existing verified payout account."""
        self.settings.mobile_money_provider = "mpesa"
        self.settings.payout_phone_number = "0711111111"
        self.settings.payout_account_name = "Existing Seller"
        self.settings.payout_account_verified = True
        self.settings.payout_verified_at = timezone.now()
        self.settings.save()

    def set_pending_verification(
        self,
        seller_id=None,
        provider="airtel_money",
        phone_number="0722222222",
        account_name="New Seller",
        minutes_ago=0,
    ):
        """Store a simulated successful NameLookup result."""
        session = self.client.session

        session["pending_payout_verification"] = {
            "seller_id": (
                self.seller.pk
                if seller_id is None
                else seller_id
            ),
            "provider": provider,
            "phone_number": phone_number,
            "account_name": account_name,
            "verified_at": (
                timezone.now()
                - timedelta(minutes=minutes_ago)
            ).isoformat(),
            "original_account_state": get_payout_account_state(self.settings),
        }

        session.save()

    def test_cancel_keeps_existing_account(self):
        """
        Leaving the confirmation page must not
        replace the existing payout account.
        """
        self.set_existing_verified_account()
        self.set_pending_verification()

        response = self.client.get(
            reverse("users:seller_settings")
        )

        self.assertEqual(response.status_code, 200)

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )
        self.assertEqual(
            self.settings.payout_account_name,
            "Existing Seller",
        )
        self.assertTrue(
            self.settings.payout_account_verified
        )

    def test_other_seller_cannot_confirm_account(self):
        """
        Pending verification belonging to another
        seller must be rejected.
        """
        self.set_existing_verified_account()

        other_user = User.objects.create_user(
            username="otherseller",
            email="other@example.com",
            password="TestPassword123!",
            is_seller=True,
        )

        other_seller = SellerProfile.objects.get(
            user=other_user
        )

        self.set_pending_verification(
            seller_id=other_seller.pk
        )

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )

        self.assertNotIn(
            "pending_payout_verification",
            self.client.session,
        )

    def test_missing_pending_verification_rejected(self):
        """
        Confirmation without pending verification
        must not change the saved account.
        """
        self.set_existing_verified_account()

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_account_name,
            "Existing Seller",
        )

    def test_future_verification_timestamp_rejected(self):
        """
        A verification timestamp in the future
        must be rejected.
        """
        self.set_existing_verified_account()

        self.set_pending_verification(
            minutes_ago=-15
        )

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )

    def test_malformed_timestamp_rejected(self):
        """
        Invalid verification timestamps must not
        allow payout account confirmation.
        """
        self.set_existing_verified_account()
        self.set_pending_verification()

        session = self.client.session
        pending = session["pending_payout_verification"]
        pending["verified_at"] = "invalid-date"
        session["pending_payout_verification"] = pending
        session.save()

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )

    def test_get_request_does_not_save_account(self):
        """
        Viewing the confirmation page must not
        save the proposed payout account.
        """
        self.set_existing_verified_account()
        self.set_pending_verification()

        response = self.client.get(
            reverse("users:confirm_payout_account")
        )

        self.assertEqual(response.status_code, 200)

        self.assertContains(
            response,
            "New Seller",
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_account_name,
            "Existing Seller",
        )

    def test_successful_confirmation_replaces_account(self):
        """
        Confirming a valid new account should
        replace the existing verified account.
        """
        self.set_existing_verified_account()
        self.set_pending_verification()

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.mobile_money_provider,
            "airtel_money",
        )
        self.assertEqual(
            self.settings.payout_phone_number,
            "0722222222",
        )
        self.assertEqual(
            self.settings.payout_account_name,
            "New Seller",
        )
        self.assertTrue(
            self.settings.payout_account_verified
        )
        self.assertIsNotNone(
            self.settings.payout_verified_at
        )

        self.assertNotIn(
            "pending_payout_verification",
            self.client.session,
        )

    def test_confirmation_requires_login(self):
        """
        Anonymous users must not confirm
        payout account details.
        """
        self.set_pending_verification()

        self.client.logout()

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertEqual(response.status_code, 302)

        self.settings.refresh_from_db()

        self.assertFalse(
            self.settings.payout_account_verified
        )

    def test_buyer_cannot_confirm_payout_account(self):
        """
        Buyers must not access seller payout
        confirmation functionality.
        """
        buyer = User.objects.create_user(
            username="testbuyer",
            email="buyer@example.com",
            password="TestPassword123!",
            is_seller=False,
        )

        self.client.force_login(buyer)

        response = self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.assertRedirects(
            response,
            reverse("users:complete_profile"),
            fetch_redirect_response=False,
        )

    def test_old_verification_cannot_overwrite_new_account(self):
        """
        A pending verification created before
        the latest account update must not
        overwrite the newer verified account.
        """
        self.set_existing_verified_account()

        self.set_pending_verification(
            minutes_ago=5
        )

        # Simulate a newer account verification.
        self.settings.mobile_money_provider = "mpesa"
        self.settings.payout_phone_number = "0733333333"
        self.settings.payout_account_name = "Latest Seller"
        self.settings.payout_account_verified = True
        self.settings.payout_verified_at = timezone.now()
        self.settings.save()

        self.client.post(
            reverse("users:confirm_payout_account")
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_phone_number,
            "0733333333",
        )
        self.assertEqual(
            self.settings.payout_account_name,
            "Latest Seller",
        )

    
    def test_cancel_removes_pending_verification(self):
        self.set_existing_verified_account()
        self.set_pending_verification()

        response = self.client.post(
            reverse("users:cancel_payout_verification")
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.assertNotIn(
            "pending_payout_verification",
            self.client.session,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )

        self.assertEqual(
            self.settings.payout_account_name,
            "Existing Seller",
        )

        self.assertTrue(
            self.settings.payout_account_verified
        )

    
    @patch("users.views.verify_seller_payout_account")
    def test_failed_name_lookup_preserves_existing_account(
        self,
        mock_verify,
    ):
        """
        A failed NameLookup must not overwrite
        the seller's existing verified account.
        """

        self.set_existing_verified_account()

        mock_verify.side_effect = ValueError(
            "AzamPay could not verify this account."
        )

        response = self.client.post(
            reverse("users:seller_settings"),
            {
                "section": "mobile_money",
                "mobile_money-mobile_money_provider": "airtel_money",
                "mobile_money-payout_phone_number": "0722222222",
            },
        )

        self.assertRedirects(
            response,
            reverse("users:seller_settings"),
            fetch_redirect_response=False,
        )

        self.settings.refresh_from_db()

        self.assertEqual(
            self.settings.mobile_money_provider,
            "mpesa",
        )
        self.assertEqual(
            self.settings.payout_phone_number,
            "0711111111",
        )
        self.assertEqual(
            self.settings.payout_account_name,
            "Existing Seller",
        )
        self.assertTrue(
            self.settings.payout_account_verified
        )

        self.assertNotIn(
            "pending_payout_verification",
            self.client.session,
        )

        mock_verify.assert_called_once_with(
            provider="airtel_money",
            phone_number="0722222222",
        )



    def test_changed_phone_after_lookup_is_rejected(self):
        self.set_existing_verified_account()
        self.set_pending_verification()
        self.settings.payout_phone_number = "0799999999"
        self.settings.save(update_fields=["payout_phone_number"])

        response = self.client.post(reverse("users:confirm_payout_account"))
        self.assertRedirects(response, reverse("users:seller_settings"), fetch_redirect_response=False)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.payout_phone_number, "0799999999")
        self.assertEqual(self.settings.payout_account_name, "Existing Seller")
        self.assertNotIn("pending_payout_verification", self.client.session)

    def test_changed_provider_after_lookup_is_rejected(self):
        self.set_existing_verified_account()
        self.set_pending_verification()
        self.settings.mobile_money_provider = "halopesa"
        self.settings.save(update_fields=["mobile_money_provider"])

        self.client.post(reverse("users:confirm_payout_account"))
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.mobile_money_provider, "halopesa")
        self.assertEqual(self.settings.payout_phone_number, "0711111111")
        self.assertNotIn("pending_payout_verification", self.client.session)

    def test_changed_account_name_after_lookup_is_rejected(self):
        self.set_existing_verified_account()
        self.set_pending_verification()
        self.settings.payout_account_name = "Updated Account Holder"
        self.settings.save(update_fields=["payout_account_name"])

        self.client.post(reverse("users:confirm_payout_account"))
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.payout_account_name, "Updated Account Holder")
        self.assertEqual(self.settings.payout_phone_number, "0711111111")
        self.assertNotIn("pending_payout_verification", self.client.session)

    def test_missing_original_account_state_is_rejected(self):
        self.set_existing_verified_account()
        self.set_pending_verification()
        session = self.client.session
        pending = session["pending_payout_verification"]
        pending.pop("original_account_state")
        session["pending_payout_verification"] = pending
        session.save()

        response = self.client.post(reverse("users:confirm_payout_account"))
        self.assertRedirects(response, reverse("users:seller_settings"), fetch_redirect_response=False)
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.payout_phone_number, "0711111111")
        self.assertNotIn("pending_payout_verification", self.client.session)

    @patch("users.views.verify_seller_payout_account")
    def test_successful_lookup_creates_pending_state_without_saving(self, mock_verify):
        self.set_existing_verified_account()
        before = get_payout_account_state(self.settings)
        mock_verify.return_value = {"account_name": "New Seller"}

        response = self.client.post(
            reverse("users:seller_settings"),
            {
                "section": "mobile_money",
                "mobile_money-mobile_money_provider": "airtel_money",
                "mobile_money-payout_phone_number": "0722222222",
            },
        )
        self.assertRedirects(
            response, reverse("users:confirm_payout_account"),
            fetch_redirect_response=False,
        )
        pending = self.client.session["pending_payout_verification"]
        self.assertEqual(pending["original_account_state"], before)
        self.assertEqual(pending["account_name"], "New Seller")
        self.settings.refresh_from_db()
        self.assertEqual(get_payout_account_state(self.settings), before)
        mock_verify.assert_called_once_with(
            provider="airtel_money", phone_number="0722222222"
        )