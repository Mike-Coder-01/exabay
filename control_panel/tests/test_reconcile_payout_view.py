
from unittest.mock import patch
from django.test import Client
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ReconcilePayoutViewTests(TestCase):

    def setUp(self):
        User = get_user_model()

        self.admin = User.objects.create_superuser(
            username="reconcile_admin",
            email="reconcile-admin@example.com",
            password="TestPassword123!",
        )

        self.regular_user = User.objects.create_user(
            username="reconcile_regular",
            email="regular@example.com",
            password="TestPassword123!",
        )

        self.url = reverse(
            "control_panel:reconcile_payout",
            args=[1],
        )

    @patch("control_panel.views.reconcile_seller_payout")
    def test_superuser_can_reconcile(self, mock_reconcile):
        mock_reconcile.return_value = {
            "success": True,
            "status": "success",
        }

        self.client.force_login(self.admin)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        mock_reconcile.assert_called_once_with(1)

    
    @patch("control_panel.views.reconcile_seller_payout")
    def test_regular_user_cannot_reconcile(self, mock_reconcile):
        self.client.force_login(self.regular_user)

        response = self.client.post(self.url)

        # A regular user must not execute reconciliation.
        mock_reconcile.assert_not_called()

        # The request must be denied or redirected.
        self.assertIn(response.status_code, [302, 403])

        # If redirected, it must not redirect back to the
        # protected reconciliation endpoint.
        if response.status_code == 302:
            self.assertNotEqual(
                response.url,
                self.url,
            )


    @patch("control_panel.views.reconcile_seller_payout")
    def test_get_request_is_rejected(self, mock_reconcile):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        mock_reconcile.assert_not_called()

    @patch("control_panel.views.reconcile_seller_payout")
    def test_failed_reconciliation_redirects_safely(
        self,
        mock_reconcile,
    ):
        mock_reconcile.return_value = {
            "success": False,
            "message": "Manual reconciliation required.",
        }

        self.client.force_login(self.admin)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        mock_reconcile.assert_called_once_with(1)

    

    @patch("control_panel.views.reconcile_seller_payout")
    def test_reconciliation_requires_csrf_token(self, mock_reconcile):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)

        response = client.post(self.url)

        self.assertEqual(response.status_code, 403)
        mock_reconcile.assert_not_called()

