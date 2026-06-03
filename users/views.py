from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from control_panel.models import AdminNotification
from main.utils import send_custom_email
from orders.models import Order

from .forms import (
    AccountProfileForm,
    CompleteProfileForm,
    ExabayLoginForm,
    ExabayPasswordChangeForm,
    RegistrationForm,
    SellerMobileMoneySettingsForm,
    SellerNotificationSettingsForm,
    SellerStorePreferencesForm,
    SellerVerificationSettingsForm,
)
from .models import Subscriber, SellerProfile, SellerSettings
from .utils import profile_requires_onboarding


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_success_redirect(user):
    if profile_requires_onboarding(user):
        return "users:complete_profile"
    if user.is_seller:
        return getattr(settings, "SELLER_DASHBOARD_URL_NAME", "main:home")
    return "users:buyer_dashboard"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

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
        form.save()
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password1"],
        )
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Your Exxabay account has been created.")
        return redirect(auth_success_redirect(user))

    return render(request, "users/register.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("main:home")


# ---------------------------------------------------------------------------
# Profile / onboarding
# ---------------------------------------------------------------------------

@login_required
def complete_profile_view(request):
    form = CompleteProfileForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        user = form.save()

        if user.is_seller:
            _send_seller_onboarding_emails(user)

        messages.success(
            request,
            "Your Exxabay profile has been updated. "
            "We've received your seller application — expect a verification update within 24 hours."
            if user.is_seller else
            "Your Exxabay profile has been updated."
        )
        return redirect(auth_success_redirect(user))

    return render(request, "users/complete_profile.html", {"form": form})


def _send_seller_onboarding_emails(user):
    full_name = user.get_full_name() or user.username

    # --- Email to the applicant ---
    send_custom_email(
        user_email=user.email,
        username=full_name,
        subject="We've received your Exxabay seller application 🎉",
        body=(
            f"Hi {full_name},\n\n"
            "Thank you for applying to sell on Exxabay! We're excited to have you on board.\n\n"
            "Here's what happens next:\n\n"
            "  1. Our team will review your profile and submitted documents.\n"
            "  2. Verification typically begins within 24 hours.\n"
            "  3. Once approved, you'll receive a confirmation email and your seller dashboard will be fully unlocked.\n\n"
            "In the meantime, feel free to browse the seller help centre or reach out to us at "
            "support@exxabay.com if you have any questions.\n\n"
            "We look forward to welcoming you to the Exxabay marketplace.\n\n"
            "Warm regards,\n"
            "The Exxabay Team"
        ),
    )

    # --- Internal alert to Exxabay staff ---
    send_custom_email(
        user_email="info@exxabay.com",
        username="Exxabay Team",
        subject=f"New seller application — {full_name} (@{user.username})",
        body=(
            f"A new seller application has been submitted and requires review.\n\n"
            f"Applicant details:\n"
            f"  • Name:     {full_name}\n"
            f"  • Username: @{user.username}\n"
            f"  • Email:    {user.email}\n\n"
            "Action required:\n"
            "  Please log in to the Exxabay admin panel and review the submitted documents "
            "to verify this seller's identity and business details before granting full marketplace access.\n\n"
            "Review the application here:\n"
            f"  https://exxabay.com/control_panel/admin-panel/\n\n"
            "— Exxabay Automated Notifications"
        ),
    )


@login_required
def edit_profile_view(request):
    if request.method == "POST":
        user = request.user
        fields = ("first_name", "last_name", "email", "phone_number", "username")
        for field in fields:
            value = request.POST.get(field)
            if value:
                setattr(user, field, value)

        new_password1 = request.POST.get("new_password1")
        new_password2 = request.POST.get("new_password2")
        if new_password1 or new_password2:
            if new_password1 != new_password2:
                messages.error(request, "Passwords do not match.")
                return redirect("users:edit_profile")
            user.set_password(new_password1)
            update_session_auth_hash(request, user)

        user.save()
        messages.success(request, "Your profile has been updated successfully.")
        return redirect("users:edit_profile")

    return render(request, "users/buyer_dashboard.html")


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------

@login_required
def buyer_dashboard(request):
    orders = Order.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "users/buyer_dashboard.html", {
        "orders":         orders,
        "orders_paid":    orders.filter(status__in=["paid", "delivered", "shipped"]),
        "orders_pending": orders.filter(status="pending", payment__status="pending"),
    })


# ---------------------------------------------------------------------------
# Seller settings
# ---------------------------------------------------------------------------

@login_required
def seller_settings_view(request):
    if not request.user.is_seller:
        messages.error(request, "Please continue as a seller to access seller settings.")
        return redirect("users:complete_profile")

    seller, _ = SellerProfile.objects.get_or_create(user=request.user)
    seller_settings, _ = SellerSettings.objects.get_or_create(
        seller=seller,
        defaults={
            "store_display_name": seller.business_name or request.user.username,
            "support_email":      request.user.email,
            "support_phone":      request.user.phone_number or "",
            "payout_phone_number": request.user.phone_number or "",
            "payout_account_name": request.user.get_full_name() or request.user.username,
        },
    )

    section = request.POST.get("section") if request.method == "POST" else ""

    forms = {
        "account_form": AccountProfileForm(
            request.POST if section == "account" else None,
            instance=request.user,
            prefix="account",
        ),
        "verification_form": SellerVerificationSettingsForm(
            request.POST if section == "verification" else None,
            request.FILES if section == "verification" else None,
            instance=seller,
            prefix="verification",
        ),
        "store_form": SellerStorePreferencesForm(
            request.POST if section == "store" else None,
            instance=seller_settings,
            prefix="store",
        ),
        "notification_form": SellerNotificationSettingsForm(
            request.POST if section == "notifications" else None,
            instance=seller_settings,
            prefix="notifications",
        ),
        "mobile_money_form": SellerMobileMoneySettingsForm(
            request.POST if section == "mobile_money" else None,
            instance=seller_settings,
            prefix="mobile_money",
        ),
        "password_form": ExabayPasswordChangeForm(
            request.user,
            request.POST if section == "security" else None,
            prefix="security",
        ),
    }

    section_to_form = {
        "account":       "account_form",
        "verification":  "verification_form",
        "store":         "store_form",
        "notifications": "notification_form",
        "mobile_money":  "mobile_money_form",
        "security":      "password_form",
    }

    if request.method == "POST":
        form_key = section_to_form.get(section)
        if not form_key:
            messages.error(request, "Invalid settings section.")
            return redirect("users:seller_settings")

        form = forms[form_key]
        if form.is_valid():
            saved = form.save()
            if section == "security":
                update_session_auth_hash(request, saved)
            messages.success(request, "Settings updated successfully.")
            return redirect("users:seller_settings")

        messages.error(request, "Please correct the highlighted fields.")

    return render(request, "users/settings.html", {
        "seller":          seller,
        "seller_settings": seller_settings,
        **forms,
    })


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@login_required
def notifications_view(request):
    status = request.GET.get("status", "all")
    if status not in {"all", "unread", "read"}:
        status = "all"

    notifications = (
        AdminNotification.objects
        .filter(recipient=request.user)
        .select_related("sender", "related_seller", "related_order")
        .order_by("-created_at")
    )

    counts = {
        "all_count":    notifications.count(),
        "unread_count": notifications.filter(is_read=False).count(),
        "read_count":   notifications.filter(is_read=True).count(),
    }

    if status == "unread":
        notifications = notifications.filter(is_read=False)
    elif status == "read":
        notifications = notifications.filter(is_read=True)

    page_obj = Paginator(notifications, 10).get_page(request.GET.get("page"))

    return render(request, "users/notifications.html", {
        "notifications": page_obj.object_list,
        "page_obj":      page_obj,
        "status":        status,
        **counts,
    })


@login_required
@require_POST
def mark_notification_read(request, notification_id):
    notification = get_object_or_404(
        AdminNotification,
        pk=notification_id,
        recipient=request.user,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    return redirect("users:notifications")


@login_required
@require_POST
def mark_all_notifications_read(request):
    AdminNotification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).update(is_read=True)

    messages.success(request, "All notifications marked as read.")
    return redirect("users:notifications")


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

def subscribe(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request"}, status=400)

    email = request.POST.get("email", "").strip().lower()
    if not email:
        return JsonResponse({"error": "Email is required"}, status=400)

    if Subscriber.objects.filter(subscriber_email=email).exists():
        return JsonResponse({"error": f"{email} is already subscribed"}, status=400)

    Subscriber.objects.create(subscriber_email=email)

    send_custom_email(
        user_email=email,
        username=request.user.username if request.user.is_authenticated else email,
        subject="You're subscribed! Stay updated with Exxabay",
        body=(
            "You're officially subscribed to Exxabay updates 🎉\n\n"
            "We'll keep you informed about:\n"
            "- Hot deals and discounts\n"
            "- Trending products\n"
            "- New sellers and marketplace updates\n\n"
            "Thanks for being part of Exxabay."
        ),
    )

    return JsonResponse({"message": "Thanks. You are on the Exxabay updates list."}, status=200)