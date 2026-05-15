from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.shortcuts import redirect, render
from .forms import CompleteProfileForm, ExabayLoginForm, RegistrationForm
from .utils import profile_requires_onboarding


def auth_success_redirect(user):
    if profile_requires_onboarding(user):
        return "users:complete_profile"
    if user.is_seller:
        return getattr(settings, "SELLER_DASHBOARD_URL_NAME", "main:home")
    return "main:home"


def login_view(request):
    if request.user.is_authenticated:
        return redirect(auth_success_redirect(request.user))

    form = ExabayLoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        messages.success(request, "Welcome back to Exabay.")
        next_url = request.GET.get("next")
        return redirect(next_url or auth_success_redirect(form.get_user()))

    return render(request, "users/login.html", {"form": form})


def register_view(request):
    if request.user.is_authenticated:
        return redirect(auth_success_redirect(request.user))

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your Exabay account has been created.")
        return redirect(auth_success_redirect(user))

    return render(request, "users/register.html", {"form": form})


@login_required
def complete_profile_view(request):
    form = CompleteProfileForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
    )

    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, "Your Exabay profile has been updated.")
        return redirect(auth_success_redirect(user))

    return render(request, "users/complete_profile.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("main:home")
