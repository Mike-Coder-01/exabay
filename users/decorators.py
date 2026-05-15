from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .utils import seller_profile_complete


def seller_onboarding_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = request.user

        if not user.is_authenticated:
            return redirect("users:login")

        if not user.is_seller:
            messages.error(request, "Please continue as a seller to access this area.")
            return redirect("users:complete_profile")

        if not seller_profile_complete(user):
            messages.info(request, "Complete your seller profile before accessing seller tools.")
            return redirect("users:complete_profile")

        return view_func(request, *args, **kwargs)

    return wrapper