from django.test import TestCase
from .models import User, SellerProfile,User, SellerProfile
from django.test import TestCase

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