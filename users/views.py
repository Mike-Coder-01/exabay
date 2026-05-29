from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.shortcuts import redirect, render, get_object_or_404, redirect, render
from .forms import CompleteProfileForm, ExabayLoginForm, RegistrationForm
from .utils import profile_requires_onboarding
from django.core.exceptions import ValidationError
from . models import Subscriber
from orders.models import Order
from main.utils import send_custom_email
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from control_panel.models import AdminNotification

def auth_success_redirect(user):
    if profile_requires_onboarding(user):
        return "users:complete_profile"
    if user.is_seller:
        return getattr(settings, "SELLER_DASHBOARD_URL_NAME", "main:home")
    return "users:buyer_dashboard"


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


def edit_profile_view(request):

    if request.method == 'POST':

        user = request.user

        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone_number = request.POST.get('phone_number')
        username = request.POST.get('username')
        new_password1 = request.POST.get('new_password1')
        new_password2 = request.POST.get('new_password2')

        if first_name:
            user.first_name = first_name

        if last_name:
            user.last_name = last_name

        if email:
            user.email = email

        if phone_number:
            user.phone_number = phone_number

        if username:
            user.username = username

        if new_password1 and new_password2:

            if new_password1 != new_password2:

                messages.error(
                    request,
                    "Password1 does not match Password2"
                )

                return redirect('users:edit_profile')

            user.set_password(new_password1)

            # Keep user logged in
            update_session_auth_hash(
                request,
                user
            )

        user.save()

        messages.success(
            request,
            "Your profile has been updated successfully."
        )

        return redirect('users:edit_profile')

    return render(
        request,
        'users/buyer_dashboard.html'
    )

def register_view(request):
    if request.user.is_authenticated:
        return redirect(auth_success_redirect(request.user))

    form = RegistrationForm(request.POST or None)

    if request.method == "POST" and form.is_valid():

        # Create user first
        form.save()

        # Authenticate newly created user
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password1"]
        )

        # Log them in
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

@login_required
def buyer_dashboard(request):
    orders = Order.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "users/buyer_dashboard.html", {
        "orders":         orders,
        "orders_paid":    orders.filter(status__in=["paid", "delivered", "shipped"]),
        "orders_pending": orders.filter(status="pending", payment__status="pending"),
    })



from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.conf import settings
from django.shortcuts import redirect, render

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
from .models import SellerProfile, SellerSettings
from .utils import profile_requires_onboarding


def auth_success_redirect(user):
    if profile_requires_onboarding(user):
        return "users:complete_profile"
    if user.is_seller:
        return getattr(settings, "SELLER_DASHBOARD_URL_NAME", "home")
    return "home"


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
def seller_settings_view(request):
    if not request.user.is_seller:
        messages.error(request, "Please continue as a seller to access seller settings.")
        return redirect("users:complete_profile")

    seller, _created = SellerProfile.objects.get_or_create(user=request.user)
    seller_settings, _created = SellerSettings.objects.get_or_create(
        seller=seller,
        defaults={
            "store_display_name": seller.business_name or request.user.username,
            "support_email": request.user.email,
            "support_phone": request.user.phone_number or "",
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
        "account": "account_form",
        "verification": "verification_form",
        "store": "store_form",
        "notifications": "notification_form",
        "mobile_money": "mobile_money_form",
        "security": "password_form",
    }

    if request.method == "POST":
        form_key = section_to_form.get(section)
        if not form_key:
            messages.error(request, "Invalid settings section.")
            return redirect("users:seller_settings")

        form = forms[form_key]
        if form.is_valid():
            saved_object = form.save()
            if section == "security":
                update_session_auth_hash(request, saved_object)
            messages.success(request, "Settings updated successfully.")
            return redirect("users:seller_settings")

        messages.error(request, "Please correct the highlighted fields.")

    context = {
        "seller": seller,
        "seller_settings": seller_settings,
        **forms,
    }
    return render(request, "users/settings.html", context)

@login_required
def notifications_view(request):
    status = request.GET.get("status", "all")
    page_number = request.GET.get("page")

    if status not in {"all", "unread", "read"}:
        status = "all"

    notifications = (
        AdminNotification.objects
        .filter(recipient=request.user)
        .select_related("sender", "related_seller", "related_order")
        .order_by("-created_at")
    )

    all_count = notifications.count()
    unread_count = notifications.filter(is_read=False).count()
    read_count = notifications.filter(is_read=True).count()

    if status == "unread":
        notifications = notifications.filter(is_read=False)
    elif status == "read":
        notifications = notifications.filter(is_read=True)

    paginator = Paginator(notifications, 10)
    page_obj = paginator.get_page(page_number)

    return render(request, "users/notifications.html", {
        "notifications": page_obj.object_list,
        "page_obj": page_obj,
        "status": status,
        "all_count": all_count,
        "unread_count": unread_count,
        "read_count": read_count,
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


@login_required
def logout_view(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("main:home")
