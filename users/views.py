from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.shortcuts import redirect, render
from .forms import CompleteProfileForm, ExabayLoginForm, RegistrationForm
from .utils import profile_requires_onboarding
from django.core.exceptions import ValidationError
from . models import Subscriber
from main.utils import send_custom_email

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
        messages.success(request, "Welcome back to Exxabay.")
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
        messages.success(request, "Your Exxabay account has been created.")
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
        messages.success(request, "Your Exxabay profile has been updated.")
        return redirect(auth_success_redirect(user))

    return render(request, "users/complete_profile.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("main:home")


def subscribe(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request'}, status=400)

    email = request.POST.get('email')
    print("EMAIL RECEIVED:", request.POST.get("email"))
    # FIX 1: validate input
    if not email:
        return JsonResponse({'error': 'Email is required'}, status=400)

    # optional: normalize
    email = email.strip().lower()

    # already exists check
    if Subscriber.objects.filter(subscriber_email=email).exists():
        return JsonResponse(
            {'error': f'{email} already subscribed'},
            status=400
        )

    subscriber = Subscriber.objects.create(
        subscriber_email=email
    )

    send_custom_email(
        user_email=email,
        username= request.user.username if request.user else email,
        subject="You're subscribed! Stay updated with Exxabay",
        body="""You’re officially subscribed to Exxabay updates 🎉

            We’ll keep you informed about:
            - Hot deals and discounts
            - Trending products
            - New sellers and marketplace updates

            Thanks for being part of Exxabay."""
            )

    return JsonResponse(
        {'message': 'Thanks. You are on the Exxabay updates list.'},
        status=200
    )