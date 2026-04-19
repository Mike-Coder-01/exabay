from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, SellerProfile
from allauth.socialaccount.signals import pre_social_login
from django.contrib.auth import get_user_model

@receiver(post_save, sender=User)
def create_seller_profile(sender, instance, created, **kwargs):
    if created and instance.is_seller:
        SellerProfile.objects.get_or_create(user=instance)


User = get_user_model()
@receiver(pre_social_login)
def link_existing_user(sender, request, sociallogin, **kwargs):
    # Get email from Google
    email = sociallogin.account.extra_data.get('email')

    if not email:
        return

    try:
        # Check if user already exists
        user = User.objects.get(email=email)

        # Connect this Google account to existing user
        sociallogin.connect(request, user)

    except User.DoesNotExist:
        pass