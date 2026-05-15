from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.urls import reverse

from .utils import profile_requires_onboarding


class ExabayAccountAdapter(DefaultAccountAdapter):
    def get_login_redirect_url(self, request):
        user = request.user
        if user.is_authenticated and profile_requires_onboarding(user):
            return reverse("users:complete_profile")
        if user.is_authenticated and user.is_seller:
            return reverse(getattr(settings, "SELLER_DASHBOARD_URL_NAME", "main:home"))
        return reverse("main:home")


class ExabaySocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        email = data.get("email")
        if email:
            user.email = email.lower()
        return user