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
from django.db import transaction, IntegrityError
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
from control_panel.services.payout_reconciliation import (
    reconcile_seller_payout,
)
from control_panel.services.azampay_payout_callbacks import (
    verify_disbursement_callback,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from control_panel.forms import SellerPayoutResolutionRequestForm
from control_panel.models import (
    SellerPayout,
    SellerPayoutInvestigation,
    SellerPayoutResolution,
)
from control_panel.services.payout_resolution_requests import (
    request_payout_resolution,
)
from main.utils import send_custom_email
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from orders.models import SellerFulfillment
from django.db.models import Q
from django.utils import timezone
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods

from control_panel.forms import SellerPayoutInvestigationForm
from control_panel.models import SellerPayout
import logging

logger = logging.getLogger(__name__)



def validate_payout_items(payout):
    """
    Return an error message if the payout is no longer safe.
    Return None when all items are eligible.
    """

    items = list(
        payout.order_items.select_related(
            "order",
            "order__payment",
            "fulfillment",
            "product",
        )
    )

    if not items:
        return "This payout contains no order items."

    expected_amount = Decimal("0.00")

    for item in items:
        if item.product.seller_id != payout.seller_id:
            return "An item belongs to another seller."

        if item.fulfillment_id is None:
            return "An item has no fulfillment record."

        if item.fulfillment.seller_id != payout.seller_id:
            return "Fulfillment seller mismatch."

        if not item.fulfillment.is_payout_eligible:
            return (
                f"Order item #{item.id} is not eligible "
                "for payout. Check payment, shipment or dispute."
            )

        if item.seller_price is None:
            return "An item has no seller price."

        expected_amount += item.seller_price * item.quantity

    if expected_amount != payout.amount:
        return "The payout amount does not match the seller earnings."

    return None

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
    ("refunded", "refunded"),
]

PAYOUT_ELIGIBLE_ORDER_STATUSES = ["completed"]
EXABAY_COMMISSION_RATE = Decimal("10.00")
PAYOUT_BLOCKING_STATUSES = [
    SellerPayout.STATUS_AUTHORIZED,
    SellerPayout.STATUS_PENDING,
    SellerPayout.STATUS_PROCESSING,
    SellerPayout.STATUS_SUCCESS,
    SellerPayout.STATUS_REFUNDED,
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
        try:
            send_custom_email(
                user_email=recipient.email,   
                username=recipient.username,
                subject=subject,
                body=message,                 
            )
        except Exception:
            pass                              

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




from .models import SellerPayout, SellerPayoutReservation
def seller_payable_items(seller):
    now = timezone.now()

    # --------------------------------------------------
    # STEP 1: Calculate seller and buyer totals
    # --------------------------------------------------

    # Amount owed to the seller.
    seller_line_total = ExpressionWrapper(
        F("quantity") * F("seller_price"),
        output_field=DecimalField(
            max_digits=14,
            decimal_places=2,
        ),
    )

    # Amount paid by the buyer.
    buyer_line_total = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(
            max_digits=14,
            decimal_places=2,
        ),
    )

    # --------------------------------------------------
    # STEP 2: Determine payout eligibility
    # --------------------------------------------------

    # The seller must have shipped the products.
    shipped = Q(
        fulfillment__shipped_at__isnull=False
    )

    # Administrator explicitly approved release.
    admin_released = Q(
        fulfillment__dispute_status="release"
    )

    # No dispute has been raised.
    no_dispute = Q(
        fulfillment__dispute_status="none"
    )

    # Buyer confirmed receiving the products.
    buyer_confirmed = Q(
        fulfillment__buyer_confirmed_at__isnull=False
    )

    # The 60-hour waiting period has expired.
    timer_expired = (
        Q(fulfillment__release_at__isnull=False)
        &
        Q(fulfillment__release_at__lte=now)
    )

    # Eligible when:
    # - Products have been shipped, AND
    # - Admin released the payout, OR
    # - No dispute exists and buyer confirmed,
    #   OR the 60-hour deadline expired.
    eligible_fulfillment = (
        shipped
        &
        (
            admin_released
            |
            (
                no_dispute
                &
                (
                    buyer_confirmed
                    |
                    timer_expired
                )
            )
        )
    )

    # --------------------------------------------------
    # STEP 3: Select eligible order items
    # --------------------------------------------------

    queryset = (
        OrderItem.objects
        .filter(
            product__seller=seller,
            order__payment__status="paid",
            seller_price__isnull=False,
            fulfillment__seller=seller,
        )
        .filter(
            eligible_fulfillment
        )
        # Exclude items linked to an active payout.
        .exclude(
            seller_payouts__status__in=PAYOUT_BLOCKING_STATUSES
        )
        # Exclude items already reserved in the database.
        .filter(
            payout_reservation__isnull=True
        )
        .select_related(
            "order",
            "order__payment",
            "product",
            "product__seller",
            "fulfillment",
        )
        .annotate(
            seller_line_total=seller_line_total,
            buyer_line_total=buyer_line_total,
        )
        .distinct()
    )

    return queryset

def seller_payable_summary(seller):
    items = seller_payable_items(seller)

    items = items.annotate(
        seller_line_total=ExpressionWrapper(
            F("seller_price") * F("quantity"),
            output_field=DecimalField(
                max_digits=14,
                decimal_places=2,
            ),
        ),
        buyer_line_total=ExpressionWrapper(
            F("price") * F("quantity"),
            output_field=DecimalField(
                max_digits=14,
                decimal_places=2,
            ),
        ),
    )

    summary = items.aggregate(
        seller_amount=Sum("seller_line_total"),
        gross_amount=Sum("buyer_line_total"),
        order_count=Count("order", distinct=True),
        item_count=Count("id"),
        unit_count=Sum("quantity"),
    )

    seller_amount = summary["seller_amount"] or Decimal("0.00")
    gross_amount = summary["gross_amount"] or Decimal("0.00")

    summary["gross_amount"] = gross_amount

    # Exxabay earns the difference between customer
    # price and seller's original price.
    summary["commission_amount"] = gross_amount - seller_amount

    # The seller receives the full original seller price.
    summary["amount"] = seller_amount

    summary["commission_rate"] = EXABAY_COMMISSION_RATE

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
            "can_preview": bool(
                phone_number and summary["amount"] > 0
            ),
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
            SellerPayout.objects.select_related(
                "seller",
                "seller__user",
            ),
            pk=preview_id,
            status=SellerPayout.STATUS_PREVIEWED,
        )

    # NEW: Pending manual payout resolution requests
    pending_resolutions = (
        SellerPayoutResolution.objects
        .filter(
            status=SellerPayoutResolution.STATUS_PENDING
        )
        .select_related(
            "payout",
            "payout__seller",
            "requested_by",
            "investigation",
        )
        .order_by("-created_at")
    )

    payout_summary = SellerPayout.objects.aggregate(
        success_amount=Sum(
            "amount",
            filter=Q(status=SellerPayout.STATUS_SUCCESS),
        ),
        processing_amount=Sum(
            "amount",
            filter=Q(status__in=[
                SellerPayout.STATUS_AUTHORIZED,
                SellerPayout.STATUS_PENDING,
                SellerPayout.STATUS_PROCESSING,
            ]),
        ),
        failed_amount=Sum(
            "amount",
            filter=Q(status__in=[
                SellerPayout.STATUS_FAILED,
                SellerPayout.STATUS_REVERSED,
                SellerPayout.STATUS_REFUNDED,
            ]),
        ),
        total_payouts=Count("id"),
        successful_payouts=Count(
            "id",
            filter=Q(status=SellerPayout.STATUS_SUCCESS),
        ),
    )

    payout_summary["success_amount"] = (
        payout_summary["success_amount"] or Decimal("0.00")
    )
    payout_summary["processing_amount"] = (
        payout_summary["processing_amount"] or Decimal("0.00")
    )
    payout_summary["failed_amount"] = (
        payout_summary["failed_amount"] or Decimal("0.00")
    )
    payout_summary["total_payouts"] = (
        payout_summary["total_payouts"] or 0
    )
    payout_summary["successful_payouts"] = (
        payout_summary["successful_payouts"] or 0
    )

    return render(
        request,
        "control_panel/seller_payouts.html",
        {
            "seller_rows": seller_rows,
            "payouts": payouts,
            "preview_payout": preview_payout,
            "gateway_balance": gateway_balance,
            "total_payable": total_payable,
            "payout_summary": payout_summary,
            "eligible_statuses": ", ".join(
                PAYOUT_ELIGIBLE_ORDER_STATUSES
            ),

            # NEW: Available to seller_payouts.html
            "pending_resolutions": pending_resolutions,
        },
    )


# This view:
# - Requires the seller to be logged in.
# - Accepts only POST requests.
# - Ensures the fulfillment belongs to that seller.
# - Prevents duplicate shipping actions through mark_shipped().
# - Checks that payment has been confirmed.
# - Starts the 60-hour countdown for that fulfillment only.
@login_required
@require_POST
def mark_order_shipped(request, fulfillment_id):

    with transaction.atomic():

        fulfillment = get_object_or_404(
            SellerFulfillment.objects
            .select_for_update()
            .select_related("seller", "order"),
            pk=fulfillment_id,
            seller__user=request.user,
        )

        try:
            fulfillment.mark_shipped()

        except ValidationError as error:
            messages.error(
                request,
                "; ".join(error.messages),
            )
            return redirect("control_panel:dashboard")

    messages.success(
        request,
        "Order marked as shipped. "
        "The 60-hour countdown has started.",
    )

    return redirect("control_panel:dashboard")



@superuser_required
@require_POST
def preview_seller_payout(request, seller_id):

    seller = get_object_or_404(
        SellerProfile.objects.select_related("user"),
        pk=seller_id,
        is_verified=True,
    )

    phone_number = get_seller_payout_phone(seller)
    account_name = get_seller_payout_account_name(seller)

    if not phone_number:
        messages.error(
            request,
            "Seller has no payout phone number."
        )
        return redirect("control_panel:seller_payouts")

    # --------------------------------------------------
    # STEP 1: Get currently eligible items
    # --------------------------------------------------

    items = list(
        seller_payable_items(seller)
        .select_related("fulfillment", "order")
        .order_by("pk")
    )

    if not items:
        messages.error(
            request,
            "This seller has no eligible unpaid order items."
        )
        return redirect("control_panel:seller_payouts")

    # Calculate amounts from the SAME item snapshot.
    amount = sum(
        (
            item.seller_price * item.quantity
            for item in items
        ),
        Decimal("0.00"),
    )

    gross_amount = sum(
        (
            item.price * item.quantity
            for item in items
        ),
        Decimal("0.00"),
    )

    commission_amount = gross_amount - amount

    if amount <= 0:
        messages.error(
            request,
            "The seller payout amount must be greater than zero."
        )
        return redirect("control_panel:seller_payouts")

    # --------------------------------------------------
    # STEP 2: Request ClickPesa preview
    # --------------------------------------------------

    token = generate_token()

    if not token:
        messages.error(
            request,
            "Could not authenticate with ClickPesa."
        )
        return redirect("control_panel:seller_payouts")

    order_reference = generate_payout_reference()

    response = preview_mobile_money_payout(
        token,
        amount,
        order_reference,
        phone_number,
    )

    if response is None:
        messages.error(
            request,
            "Could not reach ClickPesa payout preview."
        )
        return redirect("control_panel:seller_payouts")

    payload = parse_response_json(response)

    if response.status_code != 200:
        error_message = (
            payload.get("message", "Payout preview failed.")
            if isinstance(payload, dict)
            else "Payout preview failed."
        )

        messages.error(request, error_message)
        return redirect("control_panel:seller_payouts")

    if not isinstance(payload, dict):
        messages.error(
            request,
            "ClickPesa returned an unexpected preview response."
        )
        return redirect("control_panel:seller_payouts")

    # --------------------------------------------------
    # STEP 3: Revalidate and save the preview
    # --------------------------------------------------

    with transaction.atomic():

        # Lock seller row to serialize preview creation
        # for this seller, provided all preview paths
        # use this same lock.
        SellerProfile.objects.select_for_update().get(
            pk=seller.pk
        )

        # Lock the relevant fulfillments.
        fulfillment_ids = sorted({
            item.fulfillment_id
            for item in items
            if item.fulfillment_id is not None
        })

        list(
            SellerFulfillment.objects
            .select_for_update()
            .filter(pk__in=fulfillment_ids)
            .order_by("pk")
        )

        # Fetch currently eligible items again.
        current_items = list(
            seller_payable_items(seller)
            .filter(pk__in=[item.pk for item in items])
            .order_by("pk")
        )

        original_ids = {item.pk for item in items}
        current_ids = {item.pk for item in current_items}

        if original_ids != current_ids:
            messages.error(
                request,
                "Payout eligibility changed during preview. "
                "Please generate a new preview."
            )
            return redirect("control_panel:seller_payouts")

        # Recheck amount in case an item changed.
        current_amount = sum(
            (
                item.seller_price * item.quantity
                for item in current_items
            ),
            Decimal("0.00"),
        )

        if current_amount != amount:
            messages.error(
                request,
                "Seller payout amount changed. "
                "Please generate a new preview."
            )
            return redirect("control_panel:seller_payouts")

        payout = SellerPayout.objects.create(
            seller=seller,
            created_by=request.user,
            gross_amount=gross_amount,
            commission_rate=Decimal("10.00"),
            commission_amount=commission_amount,
            amount=amount,
            currency="TZS",
            phone_number=phone_number,
            account_name=account_name,
            order_reference=order_reference,
            status=SellerPayout.STATUS_PREVIEWED,
            channel_provider=payload.get(
                "channelProvider", ""
            ),
            clickpesa_fee=extract_payout_fee(payload),
            clickpesa_total_deducted=extract_total_deducted(
                payload
            ),
            preview_response=payload,
        )

        payout.order_items.set(current_items)

    messages.success(
        request,
        "Payout preview is ready. Review it before sending funds."
    )

    return redirect(
        f"{reverse('control_panel:seller_payouts')}"
        f"?preview={payout.id}"
    )






import json
import logging
from decimal import Decimal, InvalidOperation

from django.db import DatabaseError, IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from control_panel.models import SellerPayout
from control_panel.services.azampay_payouts import (
    generate_disbursement_token,
    query_payout_status,
)

logger = logging.getLogger(__name__)

MAX_CALLBACK_BYTES = 16_384

ACTIVE_STATUSES = (
    SellerPayout.STATUS_PENDING,
    SellerPayout.STATUS_PROCESSING,
)

TERMINAL_STATUSES = (
    SellerPayout.STATUS_SUCCESS,
    SellerPayout.STATUS_FAILED,
    SellerPayout.STATUS_REVERSED,
    SellerPayout.STATUS_REFUNDED,
)


def normalize_provider(value):
    """
    Normalize provider names for comparison.
    Example: Azampesa and azampesa.
    """
    if not isinstance(value, str):
        return ""

    return value.strip().casefold()


def parse_positive_amount(value):
    """
    Parse an amount safely without using float.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError("Invalid amount")

    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid amount")

    if not amount.is_finite() or amount <= 0:
        raise ValueError("Invalid amount")

    return amount


@csrf_exempt
@require_POST
def azampay_disbursement_callback(request):

    # ---------------------------------------------
    # STEP 1: Validate request size and JSON
    # ---------------------------------------------

    if len(request.body) > MAX_CALLBACK_BYTES:
        return JsonResponse(
            {"error": "Payload too large"},
            status=413,
        )

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {"error": "Invalid JSON payload"},
            status=400,
        )

    if not isinstance(payload, dict):
        return JsonResponse(
            {"error": "Expected a JSON object"},
            status=400,
        )

    # ---------------------------------------------
    # STEP 2: Extract callback fields
    # ---------------------------------------------

    reference = payload.get("initiatorReferenceId")
    pg_reference = payload.get("pgReferenceId")
    operator = payload.get("operator")

    if not all(
        isinstance(value, str) and value.strip()
        for value in (reference, pg_reference, operator)
    ):
        return JsonResponse(
            {"error": "Missing transaction identifiers"},
            status=400,
        )

    reference = reference.strip()
    pg_reference = pg_reference.strip()
    operator = operator.strip()

    # Validate callback amount if provided.
    try:
        callback_amount = (
            parse_positive_amount(payload["amount"])
            if "amount" in payload
            else None
        )
    except ValueError:
        return JsonResponse(
            {"error": "Invalid callback amount"},
            status=400,
        )

    logger.info(
        "AzamPay disbursement callback received: "
        "reference=%s pg_reference=%s",
        reference,
        pg_reference,
    )

    # ---------------------------------------------
    # STEP 3: Find Exxabay payout
    # ---------------------------------------------

    try:
        payout = SellerPayout.objects.get(
            order_reference=reference,
        )
    except SellerPayout.DoesNotExist:
        logger.warning(
            "Unknown AzamPay payout reference: %s",
            reference,
        )

        return JsonResponse(
            {"error": "Unknown payout reference"},
            status=404,
        )

    # ---------------------------------------------
    # STEP 4: Check payout state
    # ---------------------------------------------

    if payout.status in TERMINAL_STATUSES:
        if (
            payout.pg_reference_id == pg_reference
            and payout.status == SellerPayout.STATUS_SUCCESS
        ):
            return JsonResponse(
                {"message": "Payout already completed"},
                status=200,
            )

        # Do not silently accept a conflicting callback
        # for an already finalized payout.
        logger.warning(
            "Callback for terminal payout: payout=%s status=%s",
            payout.pk,
            payout.status,
        )

        return JsonResponse(
            {"error": "Payout already finalized"},
            status=409,
        )

    if payout.status not in ACTIVE_STATUSES:
        return JsonResponse(
            {"error": "Payout has not been initiated"},
            status=409,
        )

    if (
        payout.pg_reference_id
        and payout.pg_reference_id != pg_reference
    ):
        logger.warning(
            "AzamPay reference mismatch for payout %s",
            payout.pk,
        )

        return JsonResponse(
            {"error": "Transaction reference mismatch"},
            status=409,
        )

    # A blank provider must not be learned from an
    # unauthenticated callback.
    expected_provider = normalize_provider(
        payout.channel_provider
    )

    if not expected_provider:
        logger.error(
            "Missing saved destination provider: payout=%s",
            payout.pk,
        )

        return JsonResponse(
            {"error": "Payout configuration incomplete"},
            status=409,
        )

    if normalize_provider(operator) != expected_provider:
        return JsonResponse(
            {"error": "Callback provider mismatch"},
            status=400,
        )

    # ---------------------------------------------
    # STEP 5: Independently query AzamPay
    # ---------------------------------------------

    try:
        token = generate_disbursement_token()

        if not token:
            raise RuntimeError("AzamPay authentication failed")

        response = query_payout_status(
            token=token,
            pg_reference_id=pg_reference,
            bank_name=payout.channel_provider,
        )

        if response is None or response.status_code != 200:
            raise RuntimeError("AzamPay status query failed")

        verified = response.json()

        if not isinstance(verified, dict):
            raise ValueError("Invalid gateway response")

        if verified.get("success") is not True:
            raise RuntimeError(
                "AzamPay could not confirm the transaction"
            )

        # Check transaction identifiers.
        if verified.get("initiatorReferenceId") != reference:
            raise ValueError("External reference mismatch")

        if verified.get("pgReferenceId") != pg_reference:
            raise ValueError("AzamPay reference mismatch")

        # Check provider.
        verified_operator = normalize_provider(
            verified.get("operator")
        )

        if verified_operator != expected_provider:
            raise ValueError("Verified provider mismatch")

        # Check amount.
        verified_amount = parse_positive_amount(
            verified.get("amount")
        )

        if verified_amount != payout.amount:
            raise ValueError("Verified amount mismatch")

        if (
            callback_amount is not None
            and callback_amount != verified_amount
        ):
            raise ValueError("Callback amount mismatch")

        # Use only the status returned by AzamPay's
        # independently queried transaction.
        gateway_status = str(
            verified.get("status", "")
        ).strip().lower()

    except (ValueError, InvalidOperation, TypeError) as exc:
        logger.warning(
            "AzamPay verification mismatch: payout=%s error=%s",
            payout.pk,
            exc,
        )

        return JsonResponse(
            {"error": "Transaction verification mismatch"},
            status=400,
        )

    except Exception:
        logger.exception(
            "AzamPay verification unavailable: payout=%s",
            payout.pk,
        )

        return JsonResponse(
            {"error": "Verification temporarily unavailable"},
            status=503,
        )

    # ---------------------------------------------
    # STEP 6: Map verified status
    # ---------------------------------------------

    if gateway_status == "success":
        new_status = SellerPayout.STATUS_SUCCESS

    elif gateway_status in ("failed", "failure"):
        new_status = SellerPayout.STATUS_FAILED

    elif gateway_status in ("pending", "processing"):
        new_status = SellerPayout.STATUS_PROCESSING

    else:
        logger.warning(
            "Unknown AzamPay status: payout=%s status=%s",
            payout.pk,
            gateway_status,
        )

        return JsonResponse(
            {"error": "Unknown transaction status"},
            status=503,
        )

    # ---------------------------------------------
    # STEP 7: Lock and update database
    # ---------------------------------------------

    try:
        with transaction.atomic():

            locked = (
                SellerPayout.objects
                .select_for_update()
                .get(pk=payout.pk)
            )

            # Another callback or reconciliation process
            # may have updated the payout.
            if locked.status in TERMINAL_STATUSES:
                if (
                    locked.pg_reference_id == pg_reference
                    and locked.status == new_status
                ):
                    return JsonResponse(
                        {"message": "Already processed"},
                        status=200,
                    )

                return JsonResponse(
                    {"error": "Conflicting finalized payout"},
                    status=409,
                )

            if locked.status not in ACTIVE_STATUSES:
                return JsonResponse(
                    {"error": "Payout state changed"},
                    status=409,
                )

            # Prevent transaction reference replacement.
            if (
                locked.pg_reference_id
                and locked.pg_reference_id != pg_reference
            ):
                return JsonResponse(
                    {"error": "Gateway reference changed"},
                    status=409,
                )

            # Recheck financial and identity fields.
            if (
                locked.order_reference != reference
                or locked.amount != verified_amount
                or normalize_provider(
                    locked.channel_provider
                ) != expected_provider
            ):
                return JsonResponse(
                    {"error": "Payout details changed"},
                    status=409,
                )

            # Save verified transaction information.
            locked.pg_reference_id = pg_reference
            locked.fsp_reference_id = str(
                verified.get("fspReferenceId") or ""
            )
            locked.gateway_response = verified
            locked.gateway_verified_at = timezone.now()
            locked.status = new_status

            if new_status in (
                SellerPayout.STATUS_SUCCESS,
                SellerPayout.STATUS_FAILED,
            ):
                locked.completed_at = timezone.now()

            locked.save(
                update_fields=[
                    "pg_reference_id",
                    "fsp_reference_id",
                    "gateway_response",
                    "gateway_verified_at",
                    "status",
                    "completed_at",
                    "updated_at",
                ]
            )

    except (DatabaseError, IntegrityError):
        logger.exception(
            "Database error processing AzamPay callback: "
            "payout=%s",
            payout.pk,
        )

        return JsonResponse(
            {"error": "Database update temporarily unavailable"},
            status=503,
        )

    # ---------------------------------------------
    # STEP 8: Acknowledge callback
    # ---------------------------------------------

    logger.info(
        "AzamPay disbursement verified: "
        "payout=%s reference=%s status=%s",
        payout.pk,
        reference,
        new_status,
    )

    return JsonResponse(
        {
            "message": "Callback processed",
            "status": new_status,
        },
        status=200,
    )

import logging
import time

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from control_panel.services.azampay_payouts import (
    generate_disbursement_token,
    generate_disbursement_checksum,
    create_mobile_money_payout,
)

logger = logging.getLogger(__name__)


@superuser_required
@require_POST
def confirm_seller_payout(request, payout_id):

    redirect_name = "control_panel:seller_payouts"

    # STEP 1: Lock, validate and reserve
    try:
        with transaction.atomic():

            payout_info = get_object_or_404(
                SellerPayout.objects.only("id", "seller_id"),
                pk=payout_id,
                status=SellerPayout.STATUS_PREVIEWED,
            )

            # Preserve the original lock order.
            SellerProfile.objects.select_for_update().get(
                pk=payout_info.seller_id
            )

            payout = get_object_or_404(
                SellerPayout.objects
                .select_for_update()
                .select_related("seller", "seller__user"),
                pk=payout_id,
                status=SellerPayout.STATUS_PREVIEWED,
            )

            fulfillment_ids = sorted(set(
                payout.order_items
                .exclude(fulfillment_id__isnull=True)
                .values_list("fulfillment_id", flat=True)
            ))

            list(
                SellerFulfillment.objects
                .select_for_update()
                .filter(pk__in=fulfillment_ids)
                .order_by("pk")
            )

            items = list(
                payout.order_items
                .select_related("fulfillment", "product")
                .order_by("pk")
            )

            if not items:
                messages.error(
                    request,
                    "This payout contains no order items.",
                )
                return redirect(redirect_name)

            item_ids = [item.pk for item in items]

            blocking_exists = (
                OrderItem.objects
                .filter(
                    pk__in=item_ids,
                    seller_payouts__status__in=PAYOUT_BLOCKING_STATUSES,
                )
                .exclude(seller_payouts=payout)
                .exists()
            )

            if blocking_exists:
                messages.error(
                    request,
                    "One or more items belong to another active payout.",
                )
                return redirect(redirect_name)

            reserved_exists = (
                SellerPayoutReservation.objects
                .filter(order_item_id__in=item_ids)
                .exists()
            )

            if reserved_exists:
                messages.error(
                    request,
                    "One or more items are already reserved.",
                )
                return redirect(redirect_name)

            error = validate_payout_items(payout)

            if error:
                messages.error(request, error)
                return redirect(redirect_name)

            # Validate AzamPay destination before reserving.
            if not all([
                payout.account_name.strip(),
                payout.phone_number.strip(),
                payout.channel_provider.strip(),
            ]):
                messages.error(
                    request,
                    "Payout requires a verified destination "
                    "name, phone number and provider.",
                )
                return redirect(redirect_name)

            if payout.currency != "TZS" or payout.amount <= 0:
                messages.error(
                    request,
                    "Invalid payout amount or currency.",
                )
                return redirect(redirect_name)

            SellerPayoutReservation.objects.bulk_create([
                SellerPayoutReservation(
                    payout=payout,
                    order_item=item,
                )
                for item in items
            ])

            payout.status = SellerPayout.STATUS_PENDING
            payout.failure_reason = ""
            payout.save(
                update_fields=[
                    "status",
                    "failure_reason",
                    "updated_at",
                ]
            )

            # Snapshot values after validation.
            amount = payout.amount
            reference = payout.order_reference
            phone = payout.phone_number
            destination_name = payout.account_name
            bank_name = payout.channel_provider
            seller_user = payout.seller.user

    except IntegrityError:
        logger.warning(
            "Duplicate payout reservation prevented: %s",
            payout_id,
        )
        messages.error(
            request,
            "Payout reservation conflict. No transfer was sent.",
        )
        return redirect(redirect_name)

    # STEP 2: Authenticate with AzamPay
    try:
        token = generate_disbursement_token()
    except Exception:
        logger.exception(
            "AzamPay authentication error: payout=%s",
            payout_id,
        )
        token = None

    if not token:
        SellerPayout.objects.filter(
            pk=payout_id,
            status=SellerPayout.STATUS_PENDING,
        ).update(
            failure_reason=(
                "AzamPay authentication failed. "
                "Payout remains reserved for review."
            )
        )

        messages.error(
            request,
            "AzamPay authentication failed. "
            "Payout remains reserved.",
        )
        return redirect(redirect_name)

    # STEP 3: Generate checksum
    source = settings.AZAMPAY_DISBURSEMENT_SOURCE
    epoch_date = int(time.time())

    try:
        checksum = generate_disbursement_checksum(
            source_account=source["accountNumber"],
            destination_account=phone,
            currency="TZS",
            amount=str(amount),
            epoch_date=epoch_date,
            external_reference_id=reference,
            public_key_pem=settings.AZAMPAY_DISBURSEMENT_PUBLIC_KEY,
        )

    except Exception:
        logger.exception(
            "AzamPay checksum generation failed: payout=%s",
            payout_id,
        )

        SellerPayout.objects.filter(
            pk=payout_id,
            status=SellerPayout.STATUS_PENDING,
        ).update(
            failure_reason="Checksum generation failed."
        )

        messages.error(
            request,
            "Could not prepare AzamPay payout. "
            "Reservation remains active.",
        )
        return redirect(redirect_name)

    # STEP 4: Submit to AzamPay
    #
    # Do not automatically retry this request.
    try:
        response = create_mobile_money_payout(
            token=token,
            amount=amount,
            order_reference=reference,
            phone_number=phone,
            source=source,
            destination_name=destination_name,
            bank_name=bank_name,
            transfer_type="MobileMoney",
            checksum=checksum,
            date_in_epoch=epoch_date,
        )

    except Exception:
        logger.exception(
            "AzamPay disbursement request error: payout=%s",
            payout_id,
        )
        response = None

    # STEP 5: Handle missing response
    if response is None:
        SellerPayout.objects.filter(
            pk=payout_id,
            status=SellerPayout.STATUS_PENDING,
        ).update(
            failure_reason=(
                "Disbursement outcome unknown. "
                "Reconcile with AzamPay before retrying."
            )
        )

        messages.warning(
            request,
            "AzamPay did not return a response. "
            "Payout remains reserved.",
        )
        return redirect(redirect_name)

    # STEP 6: Parse gateway response
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    accepted = (
        response.status_code in (200, 201)
        and payload.get("success") is True
        and isinstance(payload.get("pgReferenceId"), str)
        and bool(payload.get("pgReferenceId"))
    )

    if not accepted:
        # An HTTP error alone does not prove that a transfer
        # did not occur. Keep the reservation.
        SellerPayout.objects.filter(
            pk=payout_id,
            status=SellerPayout.STATUS_PENDING,
        ).update(
            gateway_response=payload,
            failure_reason=(
                "AzamPay did not confirm acceptance. "
                "Manual reconciliation required."
            ),
        )

        messages.warning(
            request,
            "AzamPay did not confirm payout acceptance. "
            "Verify before attempting another transfer.",
        )
        return redirect(redirect_name)

    pg_reference = payload["pgReferenceId"]
    gateway_status = str(
        payload.get("status", "")
    ).strip().lower()

    # Acceptance is not proof of settlement.
    if gateway_status not in (
        "pending",
        "processing",
        "success",
    ):
        logger.warning(
            "Unexpected initiation status for payout %s: %s",
            payout_id,
            gateway_status,
        )

    # STEP 7: Persist gateway reference
    #
    # The callback may already have finalized this payout.
    with transaction.atomic():

        payout = (
            SellerPayout.objects
            .select_for_update()
            .get(pk=payout_id)
        )

        if (
            payout.pg_reference_id
            and payout.pg_reference_id != pg_reference
        ):
            logger.error(
                "AzamPay reference conflict for payout %s",
                payout_id,
            )
            messages.error(
                request,
                "Gateway reference conflict. Manual review required.",
            )
            return redirect(redirect_name)

        payout.pg_reference_id = pg_reference

        # Preserve callback-verified response/status if a
        # callback was processed before this database write.
        if payout.status == SellerPayout.STATUS_PENDING:
            payout.status = SellerPayout.STATUS_PROCESSING
            payout.gateway_response = payload

        if payout.initiated_at is None:
            payout.initiated_at = timezone.now()

        payout.save(
            update_fields=[
                "pg_reference_id",
                "status",
                "gateway_response",
                "initiated_at",
                "updated_at",
            ]
        )

    # STEP 8: Notify the seller
    try:
        notify_user(
            request.user,
            seller_user,
            AdminNotification.TYPE_SELLER_MESSAGE,
            "Seller payout initiated",
            (
                f"Your Exxabay payout of Tsh {amount} "
                f"has been submitted for processing. "
                f"Reference: {reference}."
            ),
            seller=payout.seller,
        )
    except Exception:
        logger.exception(
            "Seller payout notification failed: %s",
            payout_id,
        )

    messages.success(
        request,
        "Payout submitted to AzamPay. "
        "Awaiting verified transaction outcome.",
    )

    return redirect(redirect_name)

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


@superuser_required
@require_POST
def reconcile_payout_view(request, payout_id):
    result = reconcile_seller_payout(payout_id)

    if result["success"]:
        messages.success(
            request,
            f"Payout reconciliation completed: "
            f"{result['status']}."
        )
    else:
        messages.warning(
            request,
            result["message"]
        )

    return redirect("control_panel:seller_payouts")



@superuser_required
@require_http_methods(["GET", "POST"])
def investigate_seller_payout(request, payout_id):

    payout = get_object_or_404(
        SellerPayout.objects.select_related(
            "seller",
            "seller__user",
        ),
        pk=payout_id,
    )

    if request.method == "POST":
        form = SellerPayoutInvestigationForm(
            request.POST
        )

        if form.is_valid():
            investigation = form.save(commit=False)

            investigation.payout = payout
            investigation.investigated_by = request.user
            investigation.save()

            messages.success(
                request,
                "Payout investigation recorded successfully."
            )

            return redirect(
                "control_panel:seller_payouts"
            )

    else:
        form = SellerPayoutInvestigationForm()

    investigations = payout.investigations.select_related(
        "investigated_by"
    ).all()

    return render(
        request,
        "control_panel/investigate_seller_payout.html",
        {
            "payout": payout,
            "form": form,
            "investigations": investigations,
        },
    )


@superuser_required
@require_http_methods(["GET", "POST"])
def request_seller_payout_resolution(request, payout_id):

    payout = get_object_or_404(
        SellerPayout,
        pk=payout_id,
    )

    investigations = (
        SellerPayoutInvestigation.objects
        .filter(
            payout=payout,
            outcome__in=[
                SellerPayoutInvestigation.OUTCOME_CONFIRMED_PAID,
                SellerPayoutInvestigation.OUTCOME_CONFIRMED_FAILED,
            ],
        )
        .order_by("-created_at")
    )

    pending_resolution = SellerPayoutResolution.objects.filter(
        payout=payout,
        status=SellerPayoutResolution.STATUS_PENDING,
    ).first()

    if request.method == "POST":

        form = SellerPayoutResolutionRequestForm(request.POST)

        if form.is_valid():

            investigation_id = form.cleaned_data["investigation_id"]

            result = request_payout_resolution(
                payout_id=payout.pk,
                investigation_id=investigation_id,
                requested_by=request.user,
                proposed_outcome=form.cleaned_data["proposed_outcome"],
                provider_reference=form.cleaned_data["provider_reference"],
                evidence=form.cleaned_data["evidence"],
            )

            if result["success"]:
                messages.success(
                    request,
                    "Manual payout resolution request submitted."
                )

                return redirect(
                    "control_panel:seller_payouts"
                )

            messages.error(
                request,
                result["message"],
            )

    else:
        form = SellerPayoutResolutionRequestForm()

    return render(
        request,
        "control_panel/request_payout_resolution.html",
        {
            "payout": payout,
            "investigations": investigations,
            "pending_resolution": pending_resolution,
            "form": form,
        },
    )

from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from control_panel.forms import SellerPayoutResolutionDecisionForm
from control_panel.models import SellerPayoutResolution
from control_panel.services.payout_resolution_approval import (
    decide_payout_resolution,
)



@superuser_required
@require_http_methods(["GET", "POST"])
def review_payout_resolution(request, resolution_id):
    """
    Review, approve, or reject a manual payout resolution.

    Approval does not:
    - Initiate an AzamPay transfer
    - Change the payout status
    - Remove payout reservations

    Approved resolutions can subsequently be finalized
    through the separate manual finalization workflow.
    """

    resolution = get_object_or_404(
        SellerPayoutResolution.objects.select_related(
            "payout",
            "payout__seller",
            "investigation",
            "requested_by",
            "approved_by",
            "finalization",
            "finalization__finalized_by",
        ),
        pk=resolution_id,
    )

    can_decide = (
        resolution.status == SellerPayoutResolution.STATUS_PENDING
        and resolution.requested_by_id != request.user.pk
        and resolution.payout.status in {
            SellerPayout.STATUS_PENDING,
            SellerPayout.STATUS_PROCESSING,
        }
    )

    if request.method == "POST":

        form = SellerPayoutResolutionDecisionForm(
            request.POST
        )

        if not can_decide:
            form.add_error(
                None,
                "You are not allowed to decide this resolution.",
            )

        elif form.is_valid():

            result = decide_payout_resolution(
                resolution_id=resolution.pk,
                decided_by=request.user,
                decision=form.cleaned_data["decision"],
                approval_notes=form.cleaned_data["approval_notes"],
            )

            if result["success"]:
                messages.success(
                    request,
                    result["message"],
                )

                return redirect(
                    "control_panel:seller_payouts"
                )

            form.add_error(
                None,
                result["message"],
            )

    else:
        form = SellerPayoutResolutionDecisionForm()

    return render(
        request,
        "control_panel/review_payout_resolution.html",
        {
            "resolution": resolution,
            "form": form,
            "can_decide": can_decide,
        },
    )


from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from control_panel.forms import SellerPayoutFinalizationForm
from control_panel.models import SellerPayoutResolution
from control_panel.services.payout_finalization import (
    finalize_manual_payout,
)


@superuser_required
@require_http_methods(["GET", "POST"])
def finalize_payout_resolution_view(request, resolution_id):
    resolution = get_object_or_404(
        SellerPayoutResolution.objects.select_related(
            "payout",
            "payout__seller",
            "requested_by",
            "approved_by",
        ),
        pk=resolution_id,
    )

    if request.method == "POST":
        form = SellerPayoutFinalizationForm(request.POST)

        if form.is_valid():
            result = finalize_manual_payout(
                resolution_id=resolution.pk,
                finalized_by=request.user,
                **form.cleaned_data,
            )

            if result["success"]:
                messages.success(request, result["message"])
                return redirect("control_panel:seller_payouts")

            form.add_error(None, result["message"])

    else:
        form = SellerPayoutFinalizationForm(
            initial={
                "provider_reference": resolution.provider_reference,
            }
        )

    return render(
        request,
        "control_panel/finalize_payout_resolution.html",
        {
            "resolution": resolution,
            "form": form,
        },
    )
