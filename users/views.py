
from django.conf import settings

from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required

from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone
from django.views.decorators.http import require_POST

from control_panel.models import AdminNotification
from control_panel.services.azampay_payouts import (
    verify_seller_payout_account,
)
from control_panel.models import SellerPayout, SellerPayoutAttempt
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

from .models import (
    Subscriber,
    SellerProfile,
    SellerSettings,
)

from .utils import profile_requires_onboarding

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_success_redirect(user):
    if profile_requires_onboarding(user):
        return "users:complete_profile"

    if user.is_seller:
        return getattr(
            settings,
            "SELLER_DASHBOARD_URL_NAME",
            "main:home"
        )

    return "users:buyer_dashboard"

def save_verified_payout_account(
    seller_settings,
    provider,
    phone_number,
    verified_details,
):
    """
    Save payout details after successful AzamPay NameLookup
    and seller confirmation.
    """

    with transaction.atomic():
        settings_record = SellerSettings.objects.select_for_update().get(
            pk=seller_settings.pk
        )

        settings_record.mobile_money_provider = provider
        settings_record.payout_phone_number = phone_number
        settings_record.payout_account_name = verified_details["account_name"]
        settings_record.payout_account_verified = True
        settings_record.payout_verified_at = timezone.now()

        settings_record.save(update_fields=[
            "mobile_money_provider",
            "payout_phone_number",
            "payout_account_name",
            "payout_account_verified",
            "payout_verified_at",
            "updated_at",
        ])

    return settings_record


def get_payout_account_state(seller_settings):
    """
    Return the current payout account state.

    Used to detect account changes between
    NameLookup and seller confirmation.
    """
    return {
        "provider": seller_settings.mobile_money_provider or "",
        "phone_number": seller_settings.payout_phone_number or "",
        "account_name": seller_settings.payout_account_name or "",
        "verified": seller_settings.payout_account_verified,
        "verified_at": (
            seller_settings.payout_verified_at.isoformat()
            if seller_settings.payout_verified_at
            else None
        ),
    }



@login_required
def confirm_payout_account_view(request):
    if not request.user.is_seller:
        return redirect("users:complete_profile")

    pending = request.session.get(
        "pending_payout_verification"
    )

    if not pending:
        messages.error(
            request,
            "No payout account is awaiting confirmation."
        )
        return redirect("users:seller_settings")

    seller = get_object_or_404(
        SellerProfile,
        user=request.user,
    )

    if pending.get("seller_id") != seller.pk:
        request.session.pop(
            "pending_payout_verification",
            None,
        )

        messages.error(
            request,
            "Invalid payout verification."
        )
        return redirect("users:seller_settings")

    # Validate verification timestamp.
    try:
        verified_at = timezone.datetime.fromisoformat(
            pending["verified_at"]
        )

        now = timezone.now()

        valid = (
            timezone.is_aware(verified_at)
            and verified_at <= now
            and now - verified_at
            <= timezone.timedelta(minutes=10)
        )

    except (KeyError, ValueError, TypeError):
        valid = False

    if not valid:
        request.session.pop(
            "pending_payout_verification",
            None,
        )

        messages.error(
            request,
            "Verification expired. Please try again."
        )
        return redirect("users:seller_settings")

    provider = pending.get("provider")
    phone_number = pending.get("phone_number")
    account_name = pending.get("account_name")

    valid_providers = {
        choice[0]
        for choice in SellerSettings.MOBILE_PROVIDER_CHOICES
    }

    if (
        not provider
        or provider not in valid_providers
        or not phone_number
        or not account_name
    ):
        request.session.pop(
            "pending_payout_verification",
            None,
        )

        messages.error(
            request,
            "Invalid payout account details. "
            "Please verify the account again."
        )
        return redirect("users:seller_settings")

    # Require a captured original account state.
    original_state = pending.get(
        "original_account_state"
    )

    if not isinstance(original_state, dict):
        request.session.pop(
            "pending_payout_verification",
            None,
        )

        messages.error(
            request,
            "Your payout verification must be restarted. "
            "Please verify the account again."
        )
        return redirect("users:seller_settings")

    if request.method == "POST":
        with transaction.atomic():

            # 1. Lock seller profile first.
            locked_seller = (
                SellerProfile.objects
                .select_for_update()
                .get(pk=seller.pk)
            )

            # 2. Obtain and lock payout settings.
            seller_settings, _ = (
                SellerSettings.objects.get_or_create(
                    seller=locked_seller
                )
            )

            seller_settings = (
                SellerSettings.objects
                .select_for_update()
                .get(pk=seller_settings.pk)
            )

            # 3. Check for unresolved payout attempts.
            blocking_attempt_statuses = [
                SellerPayoutAttempt.STATUS_CLAIMED,
                SellerPayoutAttempt.STATUS_SUBMITTING,
                SellerPayoutAttempt.STATUS_ACCEPTED,
                SellerPayoutAttempt.STATUS_UNKNOWN,
            ]

            blocking_payout_statuses = [
                SellerPayout.STATUS_PENDING,
                SellerPayout.STATUS_PROCESSING,
            ]

            unresolved_payout_exists = (
                SellerPayoutAttempt.objects.filter(
                    payout__seller=locked_seller,
                    status__in=blocking_attempt_statuses,
                    payout__status__in=blocking_payout_statuses,
                ).exists()
            )

            if unresolved_payout_exists:
                messages.error(
                    request,
                    "Your payout account cannot be changed "
                    "while a payout is in progress or awaiting "
                    "reconciliation. Please try again after "
                    "the payout has been resolved."
                )

                return redirect(
                    "users:seller_settings"
                )

            # 4. Reject if account details changed
            # after NameLookup verification.
            current_state = get_payout_account_state(
                seller_settings
            )

            if current_state != original_state:
                request.session.pop(
                    "pending_payout_verification",
                    None,
                )

                messages.error(
                    request,
                    "Your payout account details changed "
                    "after verification started. "
                    "Please verify the account again."
                )

                return redirect(
                    "users:seller_settings"
                )

            # 5. Additional protection against an older
            # verification replacing a newer account.
            if (
                seller_settings.payout_account_verified
                and seller_settings.payout_verified_at
                and seller_settings.payout_verified_at
                >= verified_at
            ):
                request.session.pop(
                    "pending_payout_verification",
                    None,
                )

                messages.error(
                    request,
                    "Your payout account was updated "
                    "after this verification started. "
                    "Please verify the account again."
                )

                return redirect(
                    "users:seller_settings"
                )

            # 6. Save only after seller confirmation.
            save_verified_payout_account(
                seller_settings=seller_settings,
                provider=provider,
                phone_number=phone_number,
                verified_details={
                    "account_name": account_name,
                },
            )

        request.session.pop(
            "pending_payout_verification",
            None,
        )

        messages.success(
            request,
            "Your payout account has been "
            "verified and saved successfully."
        )

        return redirect(
            "users:seller_settings"
        )

    return render(
        request,
        "users/confirm_payout_account.html",
        {
            "provider": provider,
            "phone_number": phone_number,
            "account_name": account_name,
        },
    )



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
        role = form.cleaned_data["role"]

        pending_verification = None

        if role == CompleteProfileForm.ROLE_SELLER:
            provider = form.cleaned_data.get(
                "payout_provider"
            )
            phone_number = form.cleaned_data.get(
                "payout_phone"
            )

            # Require provider and phone together.
            if bool(provider) != bool(phone_number):
                messages.error(
                    request,
                    "Enter both the payout provider "
                    "and phone number.",
                )

                return render(
                    request,
                    "users/complete_profile.html",
                    {"form": form},
                )

            if provider and phone_number:
                try:
                    verified_details = (
                        verify_seller_payout_account(
                            provider=provider,
                            phone_number=phone_number,
                        )
                    )

                except ValueError:
                    messages.error(
                        request,
                        "Unable to verify the payout account. "
                        "Please check the details and try again.",
                    )

                    return render(
                        request,
                        "users/complete_profile.html",
                        {"form": form},
                    )

                # Hold verification details temporarily.
                # Nothing is saved to SellerSettings yet.
                pending_verification = {
                    "seller_id": None,
                    "provider": provider,
                    "phone_number": phone_number,
                    "account_name": verified_details[
                        "account_name"
                    ],
                    "verified_at": timezone.now().isoformat(),
                }

        user = form.save()

        if user.is_seller:
            _send_seller_onboarding_emails(user)

            if pending_verification is not None:
                seller = SellerProfile.objects.get(
                    user=user
                )

                seller_settings, _ = (
                    SellerSettings.objects.get_or_create(
                        seller=seller
                    )
                )

                pending_verification["seller_id"] = (
                    seller.pk
                )

                pending_verification[
                    "original_account_state"
                ] = get_payout_account_state(
                    seller_settings
                )

                request.session[
                    "pending_payout_verification"
                ] = pending_verification

                return redirect(
                    "users:confirm_payout_account"
                )

        messages.success(
            request,
            "Your Exxabay profile has been updated.",
        )

        return redirect(
            auth_success_redirect(user)
        )

    return render(
        request,
        "users/complete_profile.html",
        {"form": form},
    )



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

    orders = (
        Order.objects
        .filter(user=request.user)
        .select_related("payment")
        .prefetch_related(
            "seller_fulfillments__seller",
            "seller_fulfillments__items__product",
        )
        .order_by("-created_at")
    )

    # Orders with confirmed payments
    orders_paid = orders.filter(
        payment__status="paid"
    ).exclude(
        status="cancelled"
    )

    # Orders awaiting payment
    orders_pending = orders.filter(
        status="pending",
        payment__status="pending"
    )

    return render(
        request,
        "users/buyer_dashboard.html",
        {
            "orders": orders,
            "orders_paid": orders_paid,
            "orders_pending": orders_pending,
        }
    )


# ---------------------------------------------------------------------------
# Seller settings
# ---------------------------------------------------------------------------



@login_required
def seller_settings_view(request):
    if not request.user.is_seller:
        messages.error(
            request,
            "Please continue as a seller to access seller settings."
        )
        return redirect("users:complete_profile")

    seller, _ = SellerProfile.objects.get_or_create(
        user=request.user
    )

    seller_settings, _ = SellerSettings.objects.get_or_create(
        seller=seller,
        defaults={
            "store_display_name": (
                seller.business_name or request.user.username
            ),
            "support_email": request.user.email,
            "support_phone": request.user.phone_number or "",
            "payout_phone_number": "",
            "payout_account_name": "",
        },
    )

    section = (
        request.POST.get("section")
        if request.method == "POST"
        else ""
    )

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
            messages.error(
                request,
                "Invalid settings section."
            )
            return redirect("users:seller_settings")

        form = forms[form_key]

        if form.is_valid():

            if section == "mobile_money":
                provider = form.cleaned_data[
                    "mobile_money_provider"
                ]
                phone_number = form.cleaned_data[
                    "payout_phone_number"
                ]

                # IMPORTANT:
                # ModelForm validation can modify the
                # model instance in memory.
                #
                # Retrieve a fresh copy from the database
                # to capture the actual saved account.

                saved_settings = SellerSettings.objects.get(
                    pk=seller_settings.pk
                )

                original_state = get_payout_account_state(
                    saved_settings
                )

                try:
                    verified_details = (
                        verify_seller_payout_account(
                            provider=provider,
                            phone_number=phone_number,
                        )
                    )

                except ValueError:
                    messages.error(
                        request,
                        "Unable to verify this mobile money account. "
                        "Please check the details and try again.",
                    )
                    return redirect("users:seller_settings")

                # Store verified details temporarily.
                # The existing account remains unchanged
                # until the seller confirms.

                request.session[
                    "pending_payout_verification"
                ] = {
                    "seller_id": seller.pk,
                    "provider": provider,
                    "phone_number": phone_number,
                    "account_name": verified_details[
                        "account_name"
                    ],
                    "verified_at": timezone.now().isoformat(),
                    "original_account_state": original_state,
                }

                return redirect(
                    "users:confirm_payout_account"
                )

            saved = form.save()

            if section == "security":
                update_session_auth_hash(
                    request,
                    saved
                )

            messages.success(
                request,
                "Settings updated successfully.",
            )

            return redirect("users:seller_settings")

        messages.error(
            request,
            "Please correct the highlighted fields."
        )

    return render(
        request,
        "users/settings.html",
        {
            "seller": seller,
            "seller_settings": seller_settings,
            **forms,
        },
    )

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



@login_required
def cancel_payout_verification_view(request):
    if request.method != "POST":
        return redirect("users:seller_settings")

    request.session.pop(
        "pending_payout_verification",
        None,
    )

    messages.info(
        request,
        "Payout account verification cancelled. "
        "Your existing payout account was not changed.",
    )

    return redirect("users:seller_settings")
