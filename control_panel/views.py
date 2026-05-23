from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from orders.models import Order, OrderItem
from users.models import SellerProfile, User

from .forms import ContactUserForm, SellerRejectionForm
from .models import AdminNotification, SellerVerificationReview


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
