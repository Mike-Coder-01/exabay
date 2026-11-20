
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch
from control_panel.models import SellerPayoutAttempt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from users.models import SellerProfile, SellerSettings
from products.models import Product
from orders.models import (
    Order,
    OrderItem,
    Payment,
    SellerFulfillment,
)
from control_panel.models import (
    SellerPayout,
    SellerPayoutReservation,
)


class SellerPayoutInitiationTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="test_payout_admin",
            email="admin-payout@example.com",
            password="TestPassword123!",
        )

        self.seller_user = User.objects.create_user(
            username="test_payout_seller",
            email="seller-payout@example.com",
            password="TestPassword123!",
        )

        self.buyer = User.objects.create_user(
            username="test_payout_buyer",
            email="buyer-payout@example.com",
            password="TestPassword123!",
        )

        self.seller = SellerProfile.objects.create(
            user=self.seller_user,
            business_name="Exxabay Test Seller",
            located_region="DSM",
            is_verified=True,
        )

        SellerSettings.objects.create(
            seller=self.seller,
            mobile_money_provider=SellerSettings.MOBILE_PROVIDER_MPESA,
            payout_phone_number="255700000000",
            payout_account_name="Test Seller",
            payout_account_verified=True,
            payout_verified_at=timezone.now(),
        )

        self.product = Product.objects.create(
            seller=self.seller,
            name="Test Smartphone",
            description="Phone for payout testing",
            seller_price=Decimal("1000.00"),
            price=Decimal("1100.00"),
            stock=5,
        )

        self.order = Order.objects.create(
            user=self.buyer,
            total_amount=Decimal("1100.00"),
            status="paid",
        )

        Payment.objects.create(
            order=self.order,
            amount=Decimal("1100.00"),
            method="mobile_money",
            status="paid",
            transaction_id="TEST-PAYMENT-001",
        )

        self.fulfillment = SellerFulfillment.objects.create(
            order=self.order,
            seller=self.seller,
            shipped_at=timezone.now() - timedelta(hours=61),
            release_at=timezone.now() - timedelta(hours=1),
        )

        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            price=Decimal("1100.00"),
            seller_price=Decimal("1000.00"),
            fulfillment=self.fulfillment,
        )

        self.payout = SellerPayout.objects.create(
            seller=self.seller,
            amount=Decimal("1000.00"),
            gross_amount=Decimal("1000.00"),
            commission_amount=Decimal("0.00"),
            currency="TZS",
            phone_number="255700000000",
            account_name="Test Seller",
            channel_provider="Vodacom",
            order_reference="EXX-PAYOUT-TEST-001",
            status=SellerPayout.STATUS_PREVIEWED,
        )

        self.payout.order_items.add(self.order_item)

        self.url = reverse(
            "control_panel:confirm_seller_payout",
            args=[self.payout.pk],
        )

        self.client.force_login(self.admin)

        # Mock NameLookup for legacy payout tests; never call the live API.
        # Tests with their own @patch("control_panel.views.lookup_seller_name")
        # override this default response.
        self.name_lookup_patcher = patch(
            "control_panel.views.lookup_seller_name"
        )
        self.mock_name_lookup = self.name_lookup_patcher.start()
        self.addCleanup(self.name_lookup_patcher.stop)

        self.mock_name_lookup.return_value = Mock(status_code=200)
        self.mock_name_lookup.return_value.json.return_value = {
            "status": True,
            "statusCode": 200,
            "accountNumber": self.payout.phone_number,
            "bankName": self.payout.channel_provider,
            "name": self.payout.account_name,
        }

    def assert_reserved(self):
        self.assertTrue(
            SellerPayoutReservation.objects.filter(
                payout=self.payout,
                order_item=self.order_item,
            ).exists()
        )

    # TEST 1: Successful payout initiation with NameLookup

    @patch("control_panel.views.notify_user")
    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.lookup_seller_name")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_successful_payout_initiation(
        self,
        mock_token,
        mock_checksum,
        mock_lookup,
        mock_transfer,
        mock_notify,
    ):
        # STEP 1: Mock AzamPay authentication
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        # STEP 2: Mock successful recipient verification
        mock_lookup.return_value = Mock(status_code=200)
        mock_lookup.return_value.json.return_value = {
            "status": True,
            "statusCode": 200,
            "accountNumber": self.payout.phone_number,
            "bankName": self.payout.channel_provider,
            "name": self.payout.account_name,
        }

        # STEP 3: Mock successful transfer submission
        mock_transfer.return_value = Mock(status_code=200)
        mock_transfer.return_value.json.return_value = {
            "success": True,
            "pgReferenceId": "PG-PAYOUT-001",
            "status": "processing",
        }

        # STEP 4: Confirm manual payout
        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        attempt = SellerPayoutAttempt.objects.get(
            payout=self.payout,
        )

        # STEP 5: Verify HTTP response
        self.assertEqual(response.status_code, 302)

        # STEP 6: Verify payout status
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )

        self.assertEqual(
            self.payout.pg_reference_id,
            "PG-PAYOUT-001",
        )

        # STEP 7: Verify attempt status
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )

        self.assertIsNotNone(self.payout.initiated_at)

        # STEP 8: Verify order item reservation
        self.assert_reserved()

        # STEP 9: Verify NameLookup called exactly once
        mock_lookup.assert_called_once_with(
            token="fake-token",
            bank_name=self.payout.channel_provider,
            account_number=self.payout.phone_number,
            checksum="fake-checksum",
        )

        # STEP 10: Verify transfer called exactly once
        mock_transfer.assert_called_once()

        # STEP 11: Verify transfer destination
        transfer_kwargs = mock_transfer.call_args.kwargs

        self.assertEqual(
            transfer_kwargs["phone_number"],
            self.payout.phone_number,
        )

        self.assertEqual(
            transfer_kwargs["destination_name"],
            self.payout.account_name,
        )

        self.assertEqual(
            transfer_kwargs["bank_name"],
            self.payout.channel_provider,
        )

        self.assertEqual(
            transfer_kwargs["amount"],
            self.payout.amount,
        )

        # STEP 12: Verify no recipient verification failure
        self.assertFalse(attempt.error_message)

    # TEST 3: Authentication failure

    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.generate_disbursement_token")
    def test_authentication_failure_keeps_reservation(
        self,
        mock_token,
        mock_transfer,
    ):
        mock_token.return_value = None

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )

        self.assert_reserved()
        mock_transfer.assert_not_called()

        self.assertIn(
            "authentication failed",
            self.payout.failure_reason.lower(),
        )

    # TEST 4: Network timeout

    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_network_timeout_keeps_reservation(
        self,
        mock_token,
        mock_checksum,
        mock_transfer,
    ):
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        mock_transfer.side_effect = TimeoutError(
            "AzamPay request timed out"
        )

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )

        self.assert_reserved()

        mock_transfer.assert_called_once()

        self.assertIn(
            "manual reconciliation required",
            self.payout.failure_reason.lower(),
        )

        attempt = SellerPayoutAttempt.objects.get(
            payout=self.payout
        )

        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_UNKNOWN,
        )

    # TEST 5: Ineligible fulfillment

    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.generate_disbursement_token")
    def test_ineligible_fulfillment_blocks_payout(
        self,
        mock_token,
        mock_transfer,
    ):
        self.fulfillment.dispute_status = (
            SellerFulfillment.DISPUTE_OPEN
        )

        self.fulfillment.save(
            update_fields=["dispute_status"]
        )

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PREVIEWED,
        )

        self.assertFalse(
            SellerPayoutReservation.objects.filter(
                order_item=self.order_item,
            ).exists()
        )

        mock_token.assert_not_called()
        mock_transfer.assert_not_called()

    
    @patch("control_panel.views.notify_user")
    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_early_callback_preserves_successful_payout(
        self,
        mock_token,
        mock_checksum,
        mock_transfer,
        mock_notify,
    ):
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        pg_reference = "PG-EARLY-CALLBACK-001"

        def simulate_early_callback(**kwargs):
            # The initiation request has already reserved
            # the payout but has not received AzamPay's reply.
            self.payout.refresh_from_db()

            self.assertEqual(
                self.payout.status,
                SellerPayout.STATUS_PENDING,
            )

            # Simulate the database state after an independently
            # verified success callback.
            SellerPayout.objects.filter(
                pk=self.payout.pk,
            ).update(
                status=SellerPayout.STATUS_SUCCESS,
                pg_reference_id=pg_reference,
                gateway_verified_at=timezone.now(),
                completed_at=timezone.now(),
            )

            response = Mock(status_code=200)
            response.json.return_value = {
                "success": True,
                "pgReferenceId": pg_reference,
                "status": "processing",
            }

            return response

        mock_transfer.side_effect = simulate_early_callback

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )

        self.assertEqual(
            self.payout.pg_reference_id,
            pg_reference,
        )

        self.assertIsNotNone(
            self.payout.gateway_verified_at
        )

        self.assertIsNotNone(
            self.payout.completed_at
        )

        self.assert_reserved()

        mock_transfer.assert_called_once()

    
    @patch("control_panel.views.notify_user")
    @patch("control_panel.views.query_payout_status")
    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_actual_callback_arrives_during_initiation(
        self,
        mock_token,
        mock_checksum,
        mock_transfer,
        mock_status_query,
        mock_notify,
    ):
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        pg_reference = "PG-EARLY-INTEGRATION-001"

        verified_response = Mock(status_code=200)
        verified_response.json.return_value = {
            "success": True,
            "initiatorReferenceId": self.payout.order_reference,
            "pgReferenceId": pg_reference,
            "fspReferenceId": "FSP-EARLY-001",
            "amount": "1000.00",
            "operator": "vodacom",
            "status": "success",
        }

        mock_status_query.return_value = verified_response

        callback_url = reverse(
            "control_panel:azampay_disbursement_callback"
        )

        def simulate_azam_callback(**kwargs):
            # AzamPay sends a callback before its
            # initiation response is returned.
            callback_response = self.client.post(
                callback_url,
                data={
                    "initiatorReferenceId": (
                        self.payout.order_reference
                    ),
                    "pgReferenceId": pg_reference,
                    "operator": "Vodacom",
                    "amount": "1000.00",
                },
                content_type="application/json",
            )

            self.assertEqual(
                callback_response.status_code,
                200,
                callback_response.content,
            )

            response = Mock(status_code=200)
            response.json.return_value = {
                "success": True,
                "pgReferenceId": pg_reference,
                "status": "processing",
            }

            return response

        mock_transfer.side_effect = simulate_azam_callback

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_SUCCESS,
        )
        self.assertEqual(
            self.payout.pg_reference_id,
            pg_reference,
        )
        self.assertEqual(
            self.payout.fsp_reference_id,
            "FSP-EARLY-001",
        )

        self.assertIsNotNone(
            self.payout.gateway_verified_at
        )
        self.assertIsNotNone(
            self.payout.completed_at
        )

        self.assert_reserved()

        mock_transfer.assert_called_once()
        mock_status_query.assert_called_once()

    
    @patch("control_panel.views.notify_user")
    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_manual_payout_creates_unique_transfer_attempt(
        self,
        mock_token,
        mock_checksum,
        mock_transfer,
        mock_notify,
    ):
        """
        Manual payout confirmation must create a durable
        transfer attempt before submitting to AzamPay.
        """

        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        response = Mock(status_code=200)
        response.json.return_value = {
            "success": True,
            "pgReferenceId": "PG-MANUAL-001",
            "status": "processing",
        }
        mock_transfer.return_value = response

        # Administrator is already authenticated in setUp().
        result = self.client.post(self.url)

        self.assertEqual(result.status_code, 302)

        # The payout must have a unique transfer attempt.
        attempt = SellerPayoutAttempt.objects.get(
            payout=self.payout
        )

        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )

        self.assertIsNotNone(attempt.submitting_at)
        self.assertIsNotNone(attempt.completed_at)

        self.payout.refresh_from_db()

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )
        self.assertEqual(
            self.payout.pg_reference_id,
            "PG-MANUAL-001",
        )

        self.assert_reserved()

        # Only one transfer request is permitted.
        mock_transfer.assert_called_once()

    
    # TEST: Recipient name mismatch must block transfer

    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.lookup_seller_name")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_recipient_name_mismatch_blocks_transfer(
        self,
        mock_token,
        mock_checksum,
        mock_lookup,
        mock_transfer,
    ):
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        # AzamPay returns a different account holder
        mock_lookup.return_value = Mock(status_code=200)
        mock_lookup.return_value.json.return_value = {
            "status": True,
            "statusCode": 200,
            "accountNumber": self.payout.phone_number,
            "bankName": self.payout.channel_provider,
            "name": "Different Account Holder",
        }

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        attempt = SellerPayoutAttempt.objects.get(
            payout=self.payout,
        )

        # Request redirects without sending money
        self.assertEqual(response.status_code, 302)

        # Payout remains pending for investigation
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )

        # Attempt remains claimed, with a blocking marker
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_CLAIMED,
        )

        self.assertEqual(
            attempt.error_message,
            "recipient_verification_failed",
        )

        # Reserved order items must not be released
        self.assert_reserved()

        # NameLookup happened, but no transfer was sent
        mock_lookup.assert_called_once()
        mock_transfer.assert_not_called()

        # Revalidation must also refuse this attempt
        from control_panel.services.payout_initiation import (
            mark_payout_submitting,
        )

        self.assertFalse(
            mark_payout_submitting(attempt.pk)
        )

    
    # TEST: NameLookup service failure must block transfer

    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.lookup_seller_name")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_name_lookup_unavailable_blocks_transfer(
        self,
        mock_token,
        mock_checksum,
        mock_lookup,
        mock_transfer,
    ):
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        # Simulate AzamPay NameLookup being unavailable
        mock_lookup.side_effect = TimeoutError(
            "AzamPay NameLookup request timed out"
        )

        response = self.client.post(self.url)

        self.payout.refresh_from_db()

        attempt = SellerPayoutAttempt.objects.get(
            payout=self.payout,
        )

        # The view redirects without sending money
        self.assertEqual(response.status_code, 302)

        # Payout remains pending for manual investigation
        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PENDING,
        )

        # Attempt retains its claimed status
        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_CLAIMED,
        )

        # Failure is recorded permanently until resolved
        self.assertEqual(
            attempt.error_message,
            "recipient_lookup_unavailable",
        )

        # Order items remain reserved
        self.assert_reserved()

        # No transfer request was submitted
        mock_lookup.assert_called_once()
        mock_transfer.assert_not_called()

        # Attempt cannot transition to SUBMITTING
        from control_panel.services.payout_initiation import (
            mark_payout_submitting,
        )

        self.assertFalse(
            mark_payout_submitting(attempt.pk)
        )

    
    # TEST 2: Duplicate confirmation must not transfer twice

    @patch("control_panel.views.notify_user")
    @patch("control_panel.views.create_mobile_money_payout")
    @patch("control_panel.views.lookup_seller_name")
    @patch("control_panel.views.generate_disbursement_checksum")
    @patch("control_panel.views.generate_disbursement_token")
    def test_duplicate_confirmation_does_not_transfer_twice(
        self,
        mock_token,
        mock_checksum,
        mock_lookup,
        mock_transfer,
        mock_notify,
    ):
        mock_token.return_value = "fake-token"
        mock_checksum.return_value = "fake-checksum"

        # Successful recipient verification
        mock_lookup.return_value = Mock(status_code=200)
        mock_lookup.return_value.json.return_value = {
            "status": True,
            "statusCode": 200,
            "accountNumber": self.payout.phone_number,
            "bankName": self.payout.channel_provider,
            "name": self.payout.account_name,
        }

        # AzamPay accepts the transfer request
        mock_transfer.return_value = Mock(status_code=200)
        mock_transfer.return_value.json.return_value = {
            "success": True,
            "pgReferenceId": "PG-PAYOUT-002",
            "status": "processing",
        }

        # First confirmation
        first_response = self.client.post(self.url)

        # Second confirmation of the same payout
        second_response = self.client.post(self.url)

        self.payout.refresh_from_db()

        attempt = SellerPayoutAttempt.objects.get(
            payout=self.payout,
        )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 404)

        self.assertEqual(
            self.payout.status,
            SellerPayout.STATUS_PROCESSING,
        )

        self.assertEqual(
            attempt.status,
            SellerPayoutAttempt.STATUS_ACCEPTED,
        )

        # Exactly one NameLookup and one transfer
        mock_lookup.assert_called_once()
        mock_transfer.assert_called_once()

        # Exactly one reservation for this order item
        self.assertEqual(
            SellerPayoutReservation.objects.filter(
                order_item=self.order_item,
            ).count(),
            1,
        )

        self.assert_reserved()
