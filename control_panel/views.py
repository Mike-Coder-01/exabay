from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from orders.models import Order, OrderItem
from users.models import SellerProfile, User

from .forms import ContactUserForm, SellerRejectionForm
from .models import AdminNotification, SellerPayout, SellerVerificationReview
from .payout_services import (
    create_mobile_money_payout,
    extract_payout_fee,
    extract_total_deducted,
    generate_payout_reference,
    generate_token,
    preview_mobile_money_payout,
    query_payout_status,
    retrieve_account_balance,
)


ORDER_STATUS_FILTERS = [
    ("all", "All orders"),
    ("pending", "Pending"),
    ("paid", "Paid"),
    ("processing", "Processing"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
]

ORDER_STATUS_ACTIONS = [
    ("paid", "Paid"),
    ("processing", "Processing"),
    ("completed", "Completed"),
    ("cancelled", "Cancelled"),
]

PAYOUT_ELIGIBLE_ORDER_STATUSES = ["completed"]
EXABAY_COMMISSION_RATE = Decimal("10.00")
PAYOUT_BLOCKING_STATUSES = [
    SellerPayout.STATUS_AUTHORIZED,
    SellerPayout.STATUS_PENDING,
    SellerPayout.STATUS_PROCESSING,
    SellerPayout.STATUS_SUCCESS,
]

superuser_required = user_passes_test(lambda user: user.is_authenticated and user.is_superuser)


def notify_user(admin_user, recipient, notification_type, subject, message, seller=None, order=None):
    notification = AdminNotification.objects.create(
        sender=admin_user,
        recipient=recipient,
        notification_type=notification_type,
        subject=subject,
        message=message,
        related_seller=seller,
        related_order=order,
    )

    if recipient.email:
        send_mail(
            subject,
            message,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            [recipient.email],
            fail_silently=True,
        )

    return notification


def normalize_tz_phone(phone_number):
    if not phone_number:
        return ""

    digits = "".join(char for char in str(phone_number) if char.isdigit())

    if digits.startswith("255") and len(digits) == 12:
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return f"255{digits[1:]}"
    if len(digits) == 9:
        return f"255{digits}"

    return digits


def get_seller_settings(seller):
    try:
        return seller.settings
    except Exception:
        return None


def get_seller_payout_phone(seller):
    seller_settings = get_seller_settings(seller)
    payout_phone = getattr(seller_settings, "payout_phone_number", "") if seller_settings else ""
    return normalize_tz_phone(payout_phone or seller.user.phone_number)


def get_seller_payout_account_name(seller):
    seller_settings = get_seller_settings(seller)
    account_name = getattr(seller_settings, "payout_account_name", "") if seller_settings else ""
    return account_name or seller.business_name or seller.user.get_full_name() or seller.user.username


def seller_payable_items(seller):
    line_total = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    return (
        OrderItem.objects
        .filter(
            product__seller=seller,
            order__status__in=PAYOUT_ELIGIBLE_ORDER_STATUSES,
        )
        .exclude(seller_payouts__status__in=PAYOUT_BLOCKING_STATUSES)
        .select_related("order", "product", "product__seller")
        .annotate(line_total=line_total)
    )


def seller_payable_summary(seller):
    items = seller_payable_items(seller)
    summary = items.aggregate(
        gross_amount=Sum("line_total"),
        order_count=Count("order", distinct=True),
        item_count=Count("id"),
        unit_count=Sum("quantity"),
    )
    summary["gross_amount"] = summary["gross_amount"] or Decimal("0.00")
    summary["commission_rate"] = EXABAY_COMMISSION_RATE
    summary["commission_amount"] = (
        summary["gross_amount"] * EXABAY_COMMISSION_RATE / Decimal("100.00")
    ).quantize(Decimal("0.01"))
    summary["amount"] = summary["gross_amount"] - summary["commission_amount"]
    summary["order_count"] = summary["order_count"] or 0
    summary["item_count"] = summary["item_count"] or 0
    summary["unit_count"] = summary["unit_count"] or 0
    return summary


def map_clickpesa_payout_status(status):
    normalized = (status or "").lower()
    if normalized == "success":
        return SellerPayout.STATUS_SUCCESS
    if normalized == "authorized":
        return SellerPayout.STATUS_AUTHORIZED
    if normalized == "processing":
        return SellerPayout.STATUS_PROCESSING
    if normalized == "pending":
        return SellerPayout.STATUS_PENDING
    if normalized == "failed":
        return SellerPayout.STATUS_FAILED
    if normalized == "reversed":
        return SellerPayout.STATUS_REVERSED
    if normalized == "refunded":
        return SellerPayout.STATUS_REFUNDED
    return SellerPayout.STATUS_PROCESSING


def parse_response_json(response):
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


@staff_member_required
def admin_dashboard(request):
    panel = request.GET.get("panel", "all")
    status = request.GET.get("status", "all")
    seller_status = request.GET.get("seller_status", "pending")
    seller_page_number = request.GET.get("seller_page", 1)
    order_page_number = request.GET.get("order_page", 1)
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    order_q = request.GET.get("order_q", "").strip()
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    if panel not in {"all", "sellers", "orders"}:
        panel = "all"

    sellers = SellerProfile.objects.select_related("user", "verification_review").order_by("-created_at")
    if seller_status == "verified":
        sellers = sellers.filter(is_verified=True)
    elif seller_status == "rejected":
        sellers = sellers.filter(verification_review__status=SellerVerificationReview.STATUS_REJECTED)
    elif seller_status == "pending":
        sellers = sellers.filter(is_verified=False).exclude(
            verification_review__status=SellerVerificationReview.STATUS_REJECTED
        )

    if parsed_date_from:
        sellers = sellers.filter(created_at__date__gte=parsed_date_from)
    if parsed_date_to:
        sellers = sellers.filter(created_at__date__lte=parsed_date_to)

    seller_paginator = Paginator(sellers, 10)
    sellers = seller_paginator.get_page(seller_page_number)

    orders = (
        Order.objects
        .select_related("user")
        .prefetch_related(
            "items__product",
            "items__product__seller",
            "items__product__seller__user",
            "items__product__images",
        )
        .order_by("-id")
    )
    if status != "all":
        orders = orders.filter(status=status)

    if order_q:
        if order_q.isdigit():
            orders = orders.filter(id=int(order_q))
        else:
            orders = orders.none()

    order_date_field = "created_at"
    if parsed_date_from:
        orders = orders.filter(**{f"{order_date_field}__date__gte": parsed_date_from})
    if parsed_date_to:
        orders = orders.filter(**{f"{order_date_field}__date__lte": parsed_date_to})

    order_paginator = Paginator(orders, 10)
    orders = order_paginator.get_page(order_page_number)

    line_total = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    pending_seller_filter = Q(is_verified=False) & (
        Q(verification_review__isnull=True) |
        ~Q(verification_review__status=SellerVerificationReview.STATUS_REJECTED)
    )

    seller_summary = SellerProfile.objects.aggregate(
        total_sellers=Count("id"),
        verified_sellers=Count("id", filter=Q(is_verified=True)),
        rejected_sellers=Count(
            "id",
            filter=Q(verification_review__status=SellerVerificationReview.STATUS_REJECTED),
        ),
        pending_sellers=Count("id", filter=pending_seller_filter),
    )

    order_summary = Order.objects.aggregate(
        total_orders=Count("id"),
        pending_orders=Count("id", filter=Q(status="pending")),
        paid_orders=Count("id", filter=Q(status="paid")),
        processing_orders=Count("id", filter=Q(status="processing")),
        completed_orders=Count("id", filter=Q(status="completed")),
        total_revenue=Sum("total_amount"),
    )

    sold_summary = OrderItem.objects.aggregate(
        units_sold=Sum("quantity"),
        marketplace_line_total=Sum(line_total),
    )

    order_summary["total_revenue"] = order_summary["total_revenue"] or Decimal("0.00")
    sold_summary["marketplace_line_total"] = sold_summary["marketplace_line_total"] or Decimal("0.00")
    sold_summary["units_sold"] = sold_summary["units_sold"] or 0

    recent_notifications = AdminNotification.objects.select_related(
        "recipient",
        "sender",
        "related_seller",
        "related_order",
    )[:8]

    return render(request, "control_panel/admin_dashboard.html", {
        "sellers": sellers,
        "orders": orders,
        "panel": panel,
        "seller_status": seller_status,
        "seller_summary": seller_summary,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "order_q": order_q,
        "order_status_filters": ORDER_STATUS_FILTERS,
        "order_status_actions": ORDER_STATUS_ACTIONS,
        "order_summary": order_summary,
        "sold_summary": sold_summary,
        "recent_notifications": recent_notifications,
    })


@superuser_required
def seller_payouts(request):
    preview_id = request.GET.get("preview")
    seller_page_number = request.GET.get("seller_page", 1)
    payout_page_number = request.GET.get("payout_page", 1)
    gateway_balance = None

    token = generate_token()
    if token:
        balance_response = retrieve_account_balance(token)
        if balance_response and balance_response.status_code == 200:
            balance_payload = parse_response_json(balance_response)
            if isinstance(balance_payload, list) and balance_payload:
                gateway_balance = balance_payload[0]
            elif isinstance(balance_payload, dict):
                gateway_balance = balance_payload

    sellers_qs = (
        SellerProfile.objects
        .filter(is_verified=True)
        .select_related("user")
        .order_by("business_name", "user__username")
    )

    seller_rows = []
    total_payable = Decimal("0.00")

    for seller in sellers_qs:
        summary = seller_payable_summary(seller)
        total_payable += summary["amount"]
        phone_number = get_seller_payout_phone(seller)
        seller_rows.append({
            "seller": seller,
            "settings": get_seller_settings(seller),
            "phone_number": phone_number,
            "account_name": get_seller_payout_account_name(seller),
            "summary": summary,
            "can_preview": bool(phone_number and summary["amount"] > 0),
        })

    seller_paginator = Paginator(seller_rows, 10)
    seller_rows = seller_paginator.get_page(seller_page_number)

    payouts_qs = (
        SellerPayout.objects
        .select_related("seller", "seller__user", "created_by")
        .prefetch_related("order_items")
    )
    payout_paginator = Paginator(payouts_qs, 10)
    payouts = payout_paginator.get_page(payout_page_number)

    preview_payout = None
    if preview_id:
        preview_payout = get_object_or_404(
            SellerPayout.objects.select_related("seller", "seller__user"),
            pk=preview_id,
            status=SellerPayout.STATUS_PREVIEWED,
        )

    payout_summary = SellerPayout.objects.aggregate(
        success_amount=Sum("amount", filter=Q(status=SellerPayout.STATUS_SUCCESS)),
        processing_amount=Sum("amount", filter=Q(status__in=[
            SellerPayout.STATUS_AUTHORIZED,
            SellerPayout.STATUS_PENDING,
            SellerPayout.STATUS_PROCESSING,
        ])),
        failed_amount=Sum("amount", filter=Q(status__in=[
            SellerPayout.STATUS_FAILED,
            SellerPayout.STATUS_REVERSED,
            SellerPayout.STATUS_REFUNDED,
        ])),
        total_payouts=Count("id"),
        successful_payouts=Count("id", filter=Q(status=SellerPayout.STATUS_SUCCESS)),
    )
    payout_summary["success_amount"] = payout_summary["success_amount"] or Decimal("0.00")
    payout_summary["processing_amount"] = payout_summary["processing_amount"] or Decimal("0.00")
    payout_summary["failed_amount"] = payout_summary["failed_amount"] or Decimal("0.00")
    payout_summary["total_payouts"] = payout_summary["total_payouts"] or 0
    payout_summary["successful_payouts"] = payout_summary["successful_payouts"] or 0

    return render(request, "control_panel/seller_payouts.html", {
        "seller_rows": seller_rows,
        "payouts": payouts,
        "preview_payout": preview_payout,
        "gateway_balance": gateway_balance,
        "total_payable": total_payable,
        "payout_summary": payout_summary,
        "eligible_statuses": ", ".join(PAYOUT_ELIGIBLE_ORDER_STATUSES),
    })


@superuser_required
@require_POST
def preview_seller_payout(request, seller_id):
    seller = get_object_or_404(SellerProfile.objects.select_related("user"), pk=seller_id, is_verified=True)
    phone_number = get_seller_payout_phone(seller)
    account_name = get_seller_payout_account_name(seller)

    if not phone_number:
        messages.error(request, "Seller has no payout phone number.")
        return redirect("control_panel:seller_payouts")

    items = list(seller_payable_items(seller))
    summary = seller_payable_summary(seller)
    amount = summary["amount"]

    if not items or amount <= 0:
        messages.error(request, "This seller has no completed unpaid order items.")
        return redirect("control_panel:seller_payouts")

    token = generate_token()
    if not token:
        messages.error(request, "Could not authenticate with ClickPesa.")
        return redirect("control_panel:seller_payouts")

    order_reference = generate_payout_reference()
    response = preview_mobile_money_payout(token, amount, order_reference, phone_number)

    if response is None:
        messages.error(request, "Could not reach ClickPesa payout preview.")
        return redirect("control_panel:seller_payouts")

    payload = parse_response_json(response)
    if response.status_code != 200:
        messages.error(request, payload.get("message", "Payout preview failed.") if isinstance(payload, dict) else "Payout preview failed.")
        return redirect("control_panel:seller_payouts")

    payout = SellerPayout.objects.create(
        seller=seller,
        created_by=request.user,
        gross_amount=summary["gross_amount"],
        commission_rate=summary["commission_rate"],
        commission_amount=summary["commission_amount"],
        amount=amount,
        currency="TZS",
        phone_number=phone_number,
        account_name=account_name,
        order_reference=order_reference,
        status=SellerPayout.STATUS_PREVIEWED,
        channel_provider=payload.get("channelProvider", ""),
        clickpesa_fee=extract_payout_fee(payload),
        clickpesa_total_deducted=extract_total_deducted(payload),
        preview_response=payload,
    )
    payout.order_items.set(items)

    messages.success(request, "Payout preview is ready. Review it before sending funds.")
    return redirect(f"{reverse('control_panel:seller_payouts')}?preview={payout.id}")


@superuser_required
@require_POST
def confirm_seller_payout(request, payout_id):
    with transaction.atomic():
        payout = get_object_or_404(
            SellerPayout.objects
            .select_for_update()
            .select_related("seller", "seller__user")
            .prefetch_related("order_items"),
            pk=payout_id,
            status=SellerPayout.STATUS_PREVIEWED,
        )

        blocking_exists = (
            OrderItem.objects
            .filter(
                pk__in=payout.order_items.values("pk"),
                seller_payouts__status__in=PAYOUT_BLOCKING_STATUSES,
            )
            .exclude(seller_payouts=payout)
            .exists()
        )

        if blocking_exists:
            payout.status = SellerPayout.STATUS_FAILED
            payout.failure_reason = "One or more order items are already included in another payout."
            payout.save(update_fields=["status", "failure_reason", "updated_at"])
            messages.error(request, payout.failure_reason)
            return redirect("control_panel:seller_payouts")

    token = generate_token()
    if not token:
        messages.error(request, "Could not authenticate with ClickPesa.")
        return redirect("control_panel:seller_payouts")

    response = create_mobile_money_payout(
        token,
        payout.amount,
        payout.order_reference,
        payout.phone_number,
    )

    if response is None:
        payout.status = SellerPayout.STATUS_FAILED
        payout.failure_reason = "ClickPesa payout create request failed."
        payout.save(update_fields=["status", "failure_reason", "updated_at"])
        messages.error(request, payout.failure_reason)
        return redirect("control_panel:seller_payouts")

    payload = parse_response_json(response)
    if response.status_code not in (200, 201):
        payout.status = SellerPayout.STATUS_FAILED
        payout.failure_reason = payload.get("message", "ClickPesa payout was rejected.") if isinstance(payload, dict) else "ClickPesa payout was rejected."
        payout.gateway_response = payload
        payout.save(update_fields=["status", "failure_reason", "gateway_response", "updated_at"])
        messages.error(request, payout.failure_reason)
        return redirect("control_panel:seller_payouts")

    clickpesa_status = payload.get("status", "PROCESSING") if isinstance(payload, dict) else "PROCESSING"
    payout.status = map_clickpesa_payout_status(clickpesa_status)
    payout.channel_provider = payload.get("channelProvider", payout.channel_provider) if isinstance(payload, dict) else payout.channel_provider
    payout.clickpesa_fee = extract_payout_fee(payload) if isinstance(payload, dict) else payout.clickpesa_fee
    payout.clickpesa_total_deducted = extract_total_deducted(payload) if isinstance(payload, dict) else payout.clickpesa_total_deducted
    payout.gateway_response = payload
    payout.initiated_at = timezone.now()
    if payout.status == SellerPayout.STATUS_SUCCESS:
        payout.completed_at = timezone.now()
    payout.save(update_fields=[
        "status",
        "channel_provider",
        "clickpesa_fee",
        "clickpesa_total_deducted",
        "gateway_response",
        "initiated_at",
        "completed_at",
        "updated_at",
    ])

    notify_user(
        request.user,
        payout.seller.user,
        AdminNotification.TYPE_SELLER_MESSAGE,
        "Seller payout initiated",
        f"Your Exabay payout of Tsh {payout.amount} has been initiated to {payout.phone_number}. Reference: {payout.order_reference}.",
        seller=payout.seller,
    )

    messages.success(request, f"Payout sent to ClickPesa. Current status: {payout.get_status_display()}.")
    return redirect("control_panel:seller_payouts")


@superuser_required
@require_POST
def refresh_seller_payout_status(request, payout_id):
    payout = get_object_or_404(
        SellerPayout.objects.select_related("seller", "seller__user"),
        pk=payout_id,
    )

    token = generate_token()
    if not token:
        messages.error(request, "Could not authenticate with ClickPesa.")
        return redirect("control_panel:seller_payouts")

    response = query_payout_status(token, payout.order_reference)
    if response is None:
        messages.error(request, "Could not reach ClickPesa payout status endpoint.")
        return redirect("control_panel:seller_payouts")

    payload = parse_response_json(response)
    if response.status_code != 200:
        messages.error(request, payload.get("message", "Could not refresh payout status.") if isinstance(payload, dict) else "Could not refresh payout status.")
        return redirect("control_panel:seller_payouts")

    record = payload[0] if isinstance(payload, list) and payload else payload
    clickpesa_status = record.get("status", "") if isinstance(record, dict) else ""
    payout.status = map_clickpesa_payout_status(clickpesa_status)
    payout.channel_provider = record.get("channelProvider", payout.channel_provider) if isinstance(record, dict) else payout.channel_provider
    payout.clickpesa_fee = extract_payout_fee(record) if isinstance(record, dict) else payout.clickpesa_fee
    payout.clickpesa_total_deducted = extract_total_deducted(record) if isinstance(record, dict) else payout.clickpesa_total_deducted
    payout.gateway_response = record

    if payout.status == SellerPayout.STATUS_SUCCESS and not payout.completed_at:
        payout.completed_at = timezone.now()

    payout.save(update_fields=[
        "status",
        "channel_provider",
        "clickpesa_fee",
        "clickpesa_total_deducted",
        "gateway_response",
        "completed_at",
        "updated_at",
    ])

    messages.success(request, f"Payout status refreshed: {payout.get_status_display()}.")
    return redirect("control_panel:seller_payouts")


@staff_member_required
@require_POST
def verify_seller(request, seller_id):
    seller = get_object_or_404(SellerProfile.objects.select_related("user"), pk=seller_id)

    if seller.is_verified:
        messages.info(request, f"{seller} is already verified.")
        return redirect("control_panel:dashboard")

    review, _ = SellerVerificationReview.objects.get_or_create(seller=seller)
    reason = request.POST.get(
        "reason",
        "Your seller profile has already been verified by Exabay. You can now sell with verified trust status.",
    )
    review.mark_verified(request.user, reason)

    notify_user(
        request.user,
        seller.user,
        AdminNotification.TYPE_SELLER_VERIFIED,
        "Your Exabay seller profile is verified",
        reason,
        seller=seller,
    )

    messages.success(request, f"{seller} has been verified.")
    return redirect("control_panel:dashboard")


@staff_member_required
@require_POST
def unverify_seller(request, seller_id):
    seller = get_object_or_404(SellerProfile.objects.select_related("user"), pk=seller_id)
    reason = request.POST.get(
        "reason",
        "Your Exabay seller verification has been removed. Please review your business profile and documents.",
    )
    review, _ = SellerVerificationReview.objects.get_or_create(seller=seller)
    review.mark_unverified(request.user, reason)

    notify_user(
        request.user,
        seller.user,
        AdminNotification.TYPE_SELLER_UNVERIFIED,
        "Your Exabay seller verification was removed",
        reason,
        seller=seller,
    )

    messages.success(request, f"{seller} has been unverified.")
    return redirect("control_panel:dashboard")


@staff_member_required
@require_POST
def reject_seller(request, seller_id):
    seller = get_object_or_404(SellerProfile.objects.select_related("user"), pk=seller_id)
    form = SellerRejectionForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Please provide a clear rejection reason.")
        return redirect("control_panel:dashboard")

    reason = form.cleaned_data["reason"]
    review, _ = SellerVerificationReview.objects.get_or_create(seller=seller)
    review.mark_rejected(request.user, reason)

    notify_user(
        request.user,
        seller.user,
        AdminNotification.TYPE_SELLER_REJECTED,
        "Your Exabay seller verification needs attention",
        reason,
        seller=seller,
    )

    messages.success(request, f"{seller} has been rejected with feedback.")
    return redirect("control_panel:dashboard")


@staff_member_required
@require_POST
def update_order_status(request, order_id):
    order = get_object_or_404(Order.objects.select_related("user"), pk=order_id)
    status = request.POST.get("status")

    if status not in dict(ORDER_STATUS_ACTIONS):
        messages.error(request, "Invalid order status.")
        return redirect("control_panel:dashboard")

    order.status = status
    order.save(update_fields=["status"])

    notify_user(
        request.user,
        order.user,
        AdminNotification.TYPE_ORDER_FOLLOW_UP,
        f"Order #{order.id} status updated",
        f"Your Exabay order #{order.id} is now {status}.",
        order=order,
    )

    messages.success(request, f"Order #{order.id} marked as {status}.")
    return redirect("control_panel:dashboard")


@staff_member_required
@require_POST
def contact_user(request, user_id):
    recipient = get_object_or_404(User, pk=user_id)
    form = ContactUserForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Please enter a subject and message.")
        return redirect("control_panel:dashboard")

    notification_type = request.POST.get("notification_type") or AdminNotification.TYPE_ORDER_FOLLOW_UP
    order_id = request.POST.get("order_id")
    seller_id = request.POST.get("seller_id")
    order = Order.objects.filter(pk=order_id).first() if order_id else None
    seller = SellerProfile.objects.filter(pk=seller_id).first() if seller_id else None

    notify_user(
        request.user,
        recipient,
        notification_type,
        form.cleaned_data["subject"],
        form.cleaned_data["message"],
        seller=seller,
        order=order,
    )

    messages.success(request, f"Message sent to {recipient.get_full_name() or recipient.username}.")
    return redirect("control_panel:dashboard")