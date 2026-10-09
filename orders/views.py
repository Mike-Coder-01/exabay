from decimal import Decimal
import requests
import uuid
import logging
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from products.models import Product
from .models import Cart, CartItem, Order, OrderItem, Payment, ExxabayGoOrder
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from users.decorators import seller_onboarding_required
from django.utils import timezone
from datetime import timedelta 

from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from users.models import SellerProfile
from django.core.paginator import Paginator
from django.db.models.functions import TruncDate
from django.utils.dateparse import parse_date

from users.decorators import seller_onboarding_required

from decimal import Decimal, InvalidOperation
from django.urls import reverse

logger = logging.getLogger(__name__)
from .services import (
    generate_order_reference,
    generate_token,
    initiate_ussd_push,
    preview_payment,
    validate_checksum,
    query_payment_status,
)
from orders.utility import generate_paybill_number, get_azampay_public_key, token_generation,verify_callback_signature

logger = logging.getLogger(__name__)  
# __name__ will be 'orders.views' — covered by 'orders' logger above


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_phone(raw):
    """
    Accepts:  0712345678  |  +255712345678  |  255712345678
    Returns:  255712345678   (E.164 without the '+')
    """
    if not raw:
        return None
    phone = raw.strip()
    if phone.startswith("+"):
        return phone[1:]
    if phone.startswith("0"):
        return "255" + phone[1:]
    return phone


def _cancel_order(order, payment, reason=""):
    """Atomically cancel an order and its payment, leaving the cart intact."""
    with transaction.atomic():
        payment.status = "failed"
        update_fields = ["status"]
        if hasattr(payment, "gateway_response"):
            payment.gateway_response = str(reason)[:500]
            update_fields.append("gateway_response")
        payment.save(update_fields=update_fields)

        order.status = "cancelled"
        order.save(update_fields=["status"])

    logger.info("[CANCEL] order=%s reason=%s", order.id, reason)


class InsufficientStockError(Exception):
    pass


def orderView(request):
    return render(request, "orders/orders.html")

@login_required
def cart_view(request):
    cart, created = Cart.objects.get_or_create(user=request.user)

    cart_items = cart.items.select_related(
        "product",
        "product__seller",
        "product__seller__user",
        "product__category",
    ).prefetch_related("product__images")

    return render(request, "orders/cart.html", {
        "cart": cart,
        "cart_items": cart_items,
    })


@login_required
@transaction.atomic
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, pk=product_id, is_available=True)

    if product.stock < 1:
        messages.error(request, "This product is out of stock.")
        return redirect("products:product_detail", pk=product.id)

    cart, created = Cart.objects.get_or_create(user=request.user)

    item, created = CartItem.objects.get_or_create(
        cart=cart,
        product=product,
        defaults={"quantity": 1}
    )

    if not created:
        if item.quantity + 1 > product.stock:
            messages.error(request, "Not enough stock available.")
            return redirect("orders:cart")

        item.quantity += 1
        item.save(update_fields=["quantity"])

    messages.success(request, "Product added to cart.")
    return redirect("orders:cart")


@login_required
@require_POST
@transaction.atomic
def update_cart_item(request, item_id):

    cart, created = Cart.objects.get_or_create(
        user=request.user
    )

    item = get_object_or_404(
        CartItem.objects.select_related("product"),
        pk=item_id,
        cart=cart
    )

    try:
        data = json.loads(request.body)

        quantity = int(
            data.get("quantity", item.quantity)
        )

    except (ValueError, json.JSONDecodeError):
        quantity = item.quantity

    quantity = max(1, quantity)

    if quantity > item.product.stock:
        return JsonResponse({
            "success": False,
            "message": "Not enough stock available."
        }, status=400)

    item.quantity = quantity

    item.save(update_fields=["quantity"])

    cart_total = sum(
        i.product.price * i.quantity
        for i in cart.items.select_related("product")
    )

    return JsonResponse({
        "success": True,
        "quantity": item.quantity,
        "item_subtotal": str(
            item.product.price * item.quantity
        ),
        "cart_total": str(cart_total),
    })


@login_required
@require_POST
@transaction.atomic
def remove_cart_item(request, item_id):
    cart, created = Cart.objects.get_or_create(user=request.user)

    item = get_object_or_404(
        CartItem.objects.select_related("product"),
        pk=item_id,
        cart=cart
    )

    item.delete()

    cart_total = sum(i.product.price * i.quantity for i in cart.items.select_related("product"))

    return JsonResponse({
        "success": True,
        "cart_total": str(cart_total),
        "cart_count": cart.items.count(),
    })


@login_required
def payment_status(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    try:
        payment = order.payment
    except Payment.DoesNotExist:
        return JsonResponse({"status": "unknown", "message": ""})

    # Already resolved in DB
    if payment.status in ("paid", "failed"):
        messages_map = {
            "paid":   "Payment confirmed! Your order is being processed.",
            "failed": "Payment failed or was cancelled. Please try again.",
        }
        return JsonResponse({
            "status":       payment.status,
            "order_status": order.status,
            "message":      messages_map[payment.status],
        })

    # Still pending — ask ClickPesa directly
    token = generate_token()
    if token:
        result = query_payment_status(token, payment.transaction_id)
        logger.debug("[POLL] result=%s", result)

        if result:
            clickpesa_status = result.get("status", "").upper()
            clickpesa_message = result.get("message", "")
            logger.debug("[POLL] clickpesa_status=%s", clickpesa_status)

            if clickpesa_status in ("SUCCESS", "SETTLED"):
                with transaction.atomic():
                    payment.status = "paid"
                    payment.save(update_fields=["status"])
                    order.status = "paid"
                    order.save(update_fields=["status"])
                    for item in order.items.select_related("product").select_for_update():
                        Product.objects.filter(
                            pk=item.product_id,
                            stock__gte=item.quantity,
                        ).update(stock=F("stock") - item.quantity)
                    Cart.objects.filter(user=order.user).delete()

                return JsonResponse({
                    "status": "paid",
                    "order_status": "paid",
                    "message": "Payment confirmed! Your order is being processed.",
                })

            elif clickpesa_status == "FAILED":
                with transaction.atomic():
                    payment.status = "failed"
                    payment.save(update_fields=["status"])
                    order.status = "cancelled"
                    order.save(update_fields=["status"])

                return JsonResponse({
                    "status": "failed",
                    "order_status": "cancelled",
                    "message": clickpesa_message or "Payment was cancelled or failed. Please try again.",
                })

            elif clickpesa_status == "PROCESSING":
                # ClickPesa sticks on PROCESSING after cancellation with Halopesa.
                # If it has been PROCESSING for more than 2 minutes, treat as failed.
                created_at = payment.created_at
                age = timezone.now() - created_at
                logger.debug("[POLL] PROCESSING age=%s", age)

                if age > timedelta(minutes=1):
                    logger.debug("[POLL] PROCESSING timeout — marking as failed")
                    with transaction.atomic():
                        payment.status = "failed"
                        payment.save(update_fields=["status"])
                        order.status = "cancelled"
                        order.save(update_fields=["status"])

                    return JsonResponse({
                        "status": "failed",
                        "order_status": "cancelled",
                        "message": "Payment was not completed. Please try again.",
                    })

    # Still within timeout window — keep polling
    return JsonResponse({
        "status":       "pending",
        "order_status": order.status,
        "message":      "Waiting for payment confirmation...",
    })


@csrf_exempt
@require_POST
def payment_callback(request):
    """
    Handles AzamPay MNO Checkout callbacks.

    Flow:
        1. Parse AzamPay callback
        2. Verify AzamPay RSA signature
        3. Find the Exxabay payment using utilityref
        4. Verify the payment amount
        5. Lock the payment to prevent duplicate processing
        6. Mark payment/order as paid or failed
        7. Deduct stock only once after successful payment
        8. Clear the user's cart
    """

    # ── Parse JSON body ──────────────────────────────────────────────────────
    try:
        data = json.loads(request.body.decode("utf-8"))

    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("[AZAMPAY CALLBACK] Invalid JSON")

        return JsonResponse(
            {"error": "Invalid JSON."},
            status=400,
        )

    logger.info(
        "[AZAMPAY CALLBACK] Received callback. "
        "status=%s utilityref=%s transid=%s",
        data.get("transactionstatus"),
        data.get("utilityref"),
        data.get("transid"),
    )

    # ── Extract AzamPay fields ───────────────────────────────────────────────
    transaction_status = data.get("transactionstatus")
    utility_ref = data.get("utilityref")
    external_reference = data.get("externalreference")
    operator = data.get("operator")
    amount = data.get("amount")
    trans_id = data.get("transid")
    signature = data.get("signature")

    # ── Validate required fields ─────────────────────────────────────────────
    required_fields = {
        "transactionstatus": transaction_status,
        "utilityref": utility_ref,
        "externalreference": external_reference,
        "operator": operator,
        "amount": amount,
        "signature": signature,
    }

    missing_fields = [
        field
        for field, value in required_fields.items()
        if value in (None, "")
    ]

    if missing_fields:
        logger.warning(
            "[AZAMPAY CALLBACK] Missing fields: %s",
            missing_fields,
        )

        return JsonResponse(
            {
                "error": "Missing required fields.",
                "fields": missing_fields,
            },
            status=400,
        )

    # ── Convert callback amount ──────────────────────────────────────────────
    try:
        callback_amount = Decimal(str(amount))

    except (InvalidOperation, TypeError, ValueError):
        logger.warning(
            "[AZAMPAY CALLBACK] Invalid amount: %s",
            amount,
        )

        return JsonResponse(
            {"error": "Invalid amount."},
            status=400,
        )

    # ── Get AzamPay public key ───────────────────────────────────────────────
    public_key = get_azampay_public_key(
        settings.AZAMPAY_PUBLIC_KEY_URL,
        headers={
            "Authorization": f"Bearer {token_generation()}",
        },
    )

    if not public_key:
        logger.error(
            "[AZAMPAY CALLBACK] Could not obtain AzamPay public key."
        )

        return JsonResponse(
            {"error": "Unable to verify callback."},
            status=500,
        )

    # ── Verify AzamPay signature ─────────────────────────────────────────────
    is_valid = verify_callback_signature(
        utility_ref,
        external_reference,
        transaction_status,
        operator,
        signature,
        public_key,
    )

    # If verification fails, refresh the public key once and retry
    if not is_valid:

        logger.warning(
            "[AZAMPAY CALLBACK] Signature verification failed. "
            "Refreshing public key."
        )

        public_key = get_azampay_public_key(
            settings.AZAMPAY_PUBLIC_KEY_URL,
            headers={
                "Authorization": f"Bearer {token_generation()}",
            },
            force_refresh=True,
        )

        if public_key:
            is_valid = verify_callback_signature(
                utility_ref,
                external_reference,
                transaction_status,
                operator,
                signature,
                public_key,
            )

    if not is_valid:

        logger.warning(
            "[AZAMPAY CALLBACK] Invalid signature. "
            "utilityref=%s",
            utility_ref,
        )

        return JsonResponse(
            {"error": "Invalid signature."},
            status=400,
        )

    # ── Find and lock payment ────────────────────────────────────────────────
    with transaction.atomic():

        try:
            payment = (
                Payment.objects
                .select_for_update()
                .select_related("order__user")
                .get(transaction_id=utility_ref)
            )

        except Payment.DoesNotExist:

            logger.warning(
                "[AZAMPAY CALLBACK] Payment not found. "
                "utilityref=%s",
                utility_ref,
            )

            return JsonResponse(
                {"error": "Payment not found."},
                status=404,
            )

        order = payment.order

        # ── Verify amount ────────────────────────────────────────────────────
        if callback_amount != payment.amount:

            logger.error(
                "[AZAMPAY CALLBACK] Amount mismatch. "
                "payment=%s expected=%s received=%s",
                payment.id,
                payment.amount,
                callback_amount,
            )

            return JsonResponse(
                {"error": "Payment amount mismatch."},
                status=400,
            )

        # ── Idempotency ──────────────────────────────────────────────────────
        if payment.status == "paid":

            logger.info(
                "[AZAMPAY CALLBACK] Already processed. "
                "payment=%s utilityref=%s",
                payment.id,
                utility_ref,
            )

            return JsonResponse({"ok": True})

        # ── Successful payment ───────────────────────────────────────────────
        if transaction_status.lower() == "success":

            payment.status = "paid"

            if trans_id:
                payment.gateway_response = json.dumps(data)

            payment.save(
                update_fields=[
                    "status",
                    "gateway_response",
                ]
            )

            order.status = "paid"
            order.save(update_fields=["status"])

            # ── Deduct stock atomically ──────────────────────────────────────
            for item in (
                order.items
                .select_related("product")
                .select_for_update()
            ):

                updated = Product.objects.filter(
                    pk=item.product_id,
                    stock__gte=item.quantity,
                ).update(
                    stock=F("stock") - item.quantity
                )

                if updated == 0:

                    logger.error(
                        "[AZAMPAY CALLBACK] Insufficient stock. "
                        "product=%s order=%s",
                        item.product_id,
                        order.id,
                    )

                    raise InsufficientStockError(
                        item.product.name
                    )

            # ── Clear cart ───────────────────────────────────────────────────
            Cart.objects.filter(
                user=order.user
            ).delete()

            logger.info(
                "[AZAMPAY CALLBACK] Payment successful. "
                "order=%s payment=%s",
                order.id,
                payment.id,
            )

            return JsonResponse({"ok": True})

        # ── Failed payment ───────────────────────────────────────────────────
        if transaction_status.lower() == "failed":

            payment.status = "failed"
            payment.gateway_response = json.dumps(data)

            payment.save(
                update_fields=[
                    "status",
                    "gateway_response",
                ]
            )

            order.status = "cancelled"
            order.save(update_fields=["status"])

            logger.info(
                "[AZAMPAY CALLBACK] Payment failed. "
                "order=%s payment=%s",
                order.id,
                payment.id,
            )

            return JsonResponse({"ok": True})

        # ── Unknown status ────────────────────────────────────────────────────
        logger.warning(
            "[AZAMPAY CALLBACK] Unknown transaction status: %s",
            transaction_status,
        )

        return JsonResponse(
            {"error": "Unhandled transaction status."},
            status=400,
        )

@login_required
def order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects
        .select_related("user", "payment")
        .prefetch_related(
            "items__product",
            "items__product__images",
            "items__product__seller",
            "items__product__seller__user",
        ),
        id=order_id,
        user=request.user
    )

    return render(request, "orders/order_detail.html", {
        "order": order
    })


# CONFIRM ORDER RECEIVED VIEW
# This view handles the buyer's confirmation that they have received their order.
# It only accepts POST requests from authenticated users.
# The view verifies that the order belongs to the logged-in buyer and that
# the order is currently in "delivered" status before changing it to "received".
# A database transaction and row lock are used to prevent duplicate or
# simultaneous confirmation requests from changing the same order incorrectly.
# AzamPay release will be handled separately after this confirmation step.
@login_required
@require_POST
def confirm_received(request, order_id):

    with transaction.atomic():

        order = get_object_or_404(
            Order.objects.select_for_update(),
            id=order_id,
            user=request.user,
        )

        if order.status != "delivered":
            messages.error(
                request,
                "This order cannot be confirmed as received."
            )
            return redirect(
                "orders:order_detail",
                order_id=order.id
            )

        order.status = "received"
        order.save(update_fields=["status"])

    messages.success(
        request,
        "Order confirmed as received."
    )

    return redirect(
        "users:buyer_dashboard"
    )


@seller_onboarding_required
def seller_orders(request):
    seller = request.user.sellerprofile
    status = request.GET.get("status", "all")

    line_total = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    seller_items = (
        OrderItem.objects
        .filter(product__seller=seller)
        .select_related(
            "order",
            "order__user",
            "product",
            "product__category",
            "product__seller",
        )
        .prefetch_related("product__images")
        .annotate(line_total=line_total)
        .order_by("-order_id", "-id")
    )

    if status != "all":
        seller_items = seller_items.filter(order__status=status)

    base_items = OrderItem.objects.filter(product__seller=seller)

    paid_statuses = ["paid", "processing"]
    pending_statuses = ["pending", "paid", "processing"]
    completed_statuses = ["completed"]

    summary = base_items.aggregate(
        total_revenue=Sum(line_total),
        total_units=Sum("quantity"),
        total_orders=Count("order", distinct=True),
        pending_orders=Count(
            "order",
            filter=Q(order__status__in=pending_statuses),
            distinct=True,
        ),
        paid_orders=Count(
            "order",
            filter=Q(order__status__in=paid_statuses),
            distinct=True,
        ),
        completed_orders=Count(
            "order",
            filter=Q(order__status__in=completed_statuses),
            distinct=True,
        ),
    )

    summary["total_revenue"] = summary["total_revenue"] or Decimal("0.00")
    summary["total_units"] = summary["total_units"] or 0
    summary["total_orders"] = summary["total_orders"] or 0
    summary["pending_orders"] = summary["pending_orders"] or 0
    summary["paid_orders"] = summary["paid_orders"] or 0
    summary["completed_orders"] = summary["completed_orders"] or 0

    status_filters = [
        ("all", "All orders"),
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    return render(request, "orders/seller_orders.html", {
        "seller": seller,
        "order_items": seller_items,
        "summary": summary,
        "status": status,
        "status_filters": status_filters,
    })



@seller_onboarding_required
def seller_orders(request):
    seller = request.user.sellerprofile
    status = request.GET.get("status", "all")
    page_number = request.GET.get("page")

    status_filters = [
        ("all", "All orders"),
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    valid_statuses = {value for value, _label in status_filters}

    if status not in valid_statuses:
        status = "all"

    line_total = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    seller_items = (
        OrderItem.objects
        .filter(product__seller=seller)
        .select_related(
            "order",
            "order__user",
            "product",
            "product__category",
            "product__seller",
        )
        .prefetch_related("product__images")
        .annotate(line_total=line_total)
        .order_by("-order_id", "-id")
    )

    if status != "all":
        seller_items = seller_items.filter(order__status=status)

    paginator = Paginator(seller_items, 10)
    page_obj = paginator.get_page(page_number)

    base_items = OrderItem.objects.filter(product__seller=seller)

    revenue_statuses = ["paid", "processing", "completed"]
    paid_statuses = ["paid"]
    pending_statuses = ["pending"]
    completed_statuses = ["completed"]
    cancelled_statuses = ["cancelled", "refunded"]

    summary = base_items.aggregate(
        total_revenue=Sum(
            line_total,
            filter=Q(order__status__in=revenue_statuses),
        ),
        total_units=Sum("quantity"),
        total_orders=Count("order", distinct=True),
        pending_orders=Count(
            "order",
            filter=Q(order__status__in=pending_statuses),
            distinct=True,
        ),
        paid_orders=Count(
            "order",
            filter=Q(order__status__in=paid_statuses),
            distinct=True,
        ),
        completed_orders=Count(
            "order",
            filter=Q(order__status__in=completed_statuses),
            distinct=True,
        ),
        cancelled_orders=Count(
            "order",
            filter=Q(order__status__in=cancelled_statuses),
            distinct=True,
        ),
        processing_orders=Count(
            "order",
            filter=Q(order__status="processing"),
            distinct=True,
        ),
    )

    summary["total_revenue"] = summary["total_revenue"] or Decimal("0.00")
    summary["total_units"] = summary["total_units"] or 0
    summary["total_orders"] = summary["total_orders"] or 0
    summary["pending_orders"] = summary["pending_orders"] or 0
    summary["paid_orders"] = summary["paid_orders"] or 0
    summary["completed_orders"] = summary["completed_orders"] or 0
    summary["cancelled_orders"] = summary["cancelled_orders"] or 0
    summary["processing_orders"] = summary["processing_orders"] or 0

    return render(request, "orders/seller_orders.html", {
        "seller": seller,
        "order_items": page_obj.object_list,
        "page_obj": page_obj,
        "summary": summary,
        "status": status,
        "status_filters": status_filters,
    })


@seller_onboarding_required
def seller_analytics(request):
    seller = request.user.sellerprofile
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None

    line_total = ExpressionWrapper(
        F("quantity") * F("price"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )
    inventory_value = ExpressionWrapper(
        F("price") * F("stock"),
        output_field=DecimalField(max_digits=12, decimal_places=2),
    )

    revenue_statuses = ["paid", "processing", "completed"]
    active_statuses = ["pending", "paid", "processing"]
    cancelled_statuses = ["cancelled", "refunded"]

    seller_items = (
        OrderItem.objects
        .filter(product__seller=seller)
        .select_related("order", "order__user", "product", "product__category")
        .prefetch_related("product__images")
        .annotate(line_total=line_total)
    )

    if parsed_date_from:
        seller_items = seller_items.filter(order__created_at__date__gte=parsed_date_from)

    if parsed_date_to:
        seller_items = seller_items.filter(order__created_at__date__lte=parsed_date_to)

    revenue_items = seller_items.filter(order__status__in=revenue_statuses)
    product_qs = Product.objects.filter(seller=seller)

    summary = seller_items.aggregate(
        gross_revenue=Sum(
            line_total,
            filter=Q(order__status__in=revenue_statuses),
        ),
        total_units=Sum("quantity"),
        total_orders=Count("order", distinct=True),
        revenue_orders=Count(
            "order",
            filter=Q(order__status__in=revenue_statuses),
            distinct=True,
        ),
        active_orders=Count(
            "order",
            filter=Q(order__status__in=active_statuses),
            distinct=True,
        ),
        pending_orders=Count(
            "order",
            filter=Q(order__status="pending"),
            distinct=True,
        ),
        paid_orders=Count(
            "order",
            filter=Q(order__status="paid"),
            distinct=True,
        ),
        processing_orders=Count(
            "order",
            filter=Q(order__status="processing"),
            distinct=True,
        ),
        completed_orders=Count(
            "order",
            filter=Q(order__status="completed"),
            distinct=True,
        ),
        cancelled_orders=Count(
            "order",
            filter=Q(order__status__in=cancelled_statuses),
            distinct=True,
        ),
        unique_buyers=Count("order__user", distinct=True),
    )

    for key in summary:
        summary[key] = summary[key] or 0

    gross_revenue = summary["gross_revenue"] or Decimal("0.00")
    revenue_orders = summary["revenue_orders"] or 0
    summary["average_order_value"] = (
        gross_revenue / revenue_orders
        if revenue_orders
        else Decimal("0.00")
    )
    summary["completion_rate"] = (
        round((summary["completed_orders"] / revenue_orders) * 100)
        if revenue_orders
        else 0
    )
    summary["cancellation_rate"] = (
        round((summary["cancelled_orders"] / summary["total_orders"]) * 100)
        if summary["total_orders"]
        else 0
    )

    repeat_buyers = (
        seller_items
        .values("order__user")
        .annotate(order_count=Count("order", distinct=True))
        .filter(order_count__gt=1)
        .count()
    )

    inventory_summary = product_qs.aggregate(
        total_products=Count("id"),
        active_products=Count("id", filter=Q(is_available=True)),
        inactive_products=Count("id", filter=Q(is_available=False)),
        featured_products=Count("id", filter=Q(is_featured=True)),
        low_stock_products=Count("id", filter=Q(stock__gt=0, stock__lte=5)),
        out_of_stock_products=Count("id", filter=Q(stock=0)),
        inventory_value=Sum(inventory_value),
    )

    for key in inventory_summary:
        inventory_summary[key] = inventory_summary[key] or 0

    top_products = list(
        revenue_items
        .values(
            "product_id",
            "product__name",
            "product__stock",
            "product__is_available",
            "product__category__name",
        )
        .annotate(
            units_sold=Sum("quantity"),
            revenue=Sum(line_total),
            order_count=Count("order", distinct=True),
        )
        .order_by("-revenue")[:5]
    )
    top_product_revenue = max(
        [product["revenue"] or Decimal("0.00") for product in top_products],
        default=Decimal("0.00"),
    )

    for product in top_products:
        product["revenue"] = product["revenue"] or Decimal("0.00")
        product["units_sold"] = product["units_sold"] or 0
        product["progress"] = (
            int((product["revenue"] / top_product_revenue) * 100)
            if top_product_revenue
            else 0
        )

    category_performance = list(
        revenue_items
        .values("product__category__name")
        .annotate(
            revenue=Sum(line_total),
            units_sold=Sum("quantity"),
            product_count=Count("product", distinct=True),
        )
        .order_by("-revenue")[:5]
    )

    daily_sales = list(
        revenue_items
        .annotate(day=TruncDate("order__created_at"))
        .values("day")
        .annotate(
            revenue=Sum(line_total),
            units_sold=Sum("quantity"),
            order_count=Count("order", distinct=True),
        )
        .order_by("day")
    )[-14:]
    highest_daily_revenue = max(
        [row["revenue"] or Decimal("0.00") for row in daily_sales],
        default=Decimal("0.00"),
    )

    for row in daily_sales:
        row["revenue"] = row["revenue"] or Decimal("0.00")
        row["units_sold"] = row["units_sold"] or 0
        row["order_count"] = row["order_count"] or 0
        row["progress"] = (
            int((row["revenue"] / highest_daily_revenue) * 100)
            if highest_daily_revenue
            else 0
        )

    status_breakdown = list(
        seller_items
        .values("order__status")
        .annotate(
            order_count=Count("order", distinct=True),
            units_sold=Sum("quantity"),
            value=Sum(line_total),
        )
        .order_by("order__status")
    )

    action_items = (
        seller_items
        .filter(order__status__in=active_statuses)
        .order_by("-order__created_at", "-id")[:5]
    )

    context = {
        "seller": seller,
        "seller_name": request.user.get_full_name() or request.user.username,
        "summary": summary,
        "inventory_summary": inventory_summary,
        "top_products": top_products,
        "category_performance": category_performance,
        "daily_sales": daily_sales,
        "status_breakdown": status_breakdown,
        "action_items": action_items,
        "repeat_buyers": repeat_buyers,
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "orders/seller_analytics.html", context)



BASE_FEE = Decimal('1500')
FEE_RATE = Decimal('0.01')


def calculate_fee(amount):
    amount = Decimal(str(amount))
    if amount <= 0:
        return Decimal('0')
    return BASE_FEE + (amount * FEE_RATE)


def create_exxabay_go_order(request):
    seller = SellerProfile.objects.filter(user=request.user)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    try:
        data = json.loads(request.body)
        amount_to_be_paid = Decimal(str(data['amount']))
        buyer_phone_number = data['phone']

        if amount_to_be_paid <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be greater than zero.'}, status=400)

        fee_amount = calculate_fee(amount_to_be_paid)
        total_amount = amount_to_be_paid + fee_amount

        exxabay_go_order = ExxabayGoOrder.objects.create(
            seller_profile=seller,
            amount_to_be_paid=amount_to_be_paid,
            fee_amount=fee_amount,
            total_amount=total_amount,
            buyer_phone_number=buyer_phone_number,
        )

        payment_path = reverse('orders:order_payment_detail', kwargs={'token': exxabay_go_order.token})
        payment_link = request.build_absolute_uri(payment_path)

        return JsonResponse({
            'success': True,
            'payment_link': payment_link,
            'token': str(exxabay_go_order.token),
        })

    except (KeyError, InvalidOperation, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid order data provided.'}, status=400)
    except Exception:
        logger.exception("Failed to create ExxabayGoOrder")
        return JsonResponse({'success': False, 'error': 'Could not create the order. Please try again.'}, status=400)
    

def order_payment_detail(request, token):
    order = get_object_or_404(ExxabayGoOrder, token=token)
    context = {'order': order}
    return render(request, 'orders/order_payment_detail.html', context)


from . import services as cp
import re
def initiate_order_payment(request, token):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

    order = get_object_or_404(ExxabayGoOrder, token=token)

    if order.status == ExxabayGoOrder.STATUS_PAID:
        return JsonResponse({'success': False, 'error': 'This order has already been paid.'}, status=400)

    try:
        data = json.loads(request.body)
        raw_phone = data.get('phone', '')
    except (json.JSONDecodeError, AttributeError):
        raw_phone = ''

    payer_phone = _normalize_phone(raw_phone)

    if not payer_phone or not re.match(r'^255[67]\d{8}$', payer_phone):
        return JsonResponse({'success': False, 'error': 'Please enter a valid phone number.'}, status=400)

    if not order.order_reference:
        order.order_reference = cp.generate_order_reference()
        order.save(update_fields=['order_reference'])

    auth_token = cp.generate_token()
    if not auth_token:
        logger.error("ClickPesa token generation failed for order %s", order.token)
        return JsonResponse({'success': False, 'error': 'Could not start payment. Please try again.'}, status=502)

    response = cp.initiate_ussd_push(
        token=auth_token,
        amount=order.total_amount,
        order_reference=order.order_reference,
        phone_number=payer_phone,
    )

    if response is None:
        return JsonResponse({'success': False, 'error': 'Could not reach the payment gateway. Please try again.'}, status=502)

    if response.status_code not in (200, 201):
        gateway_message = None
        try:
            gateway_body = response.json()
            raw_message = gateway_body.get('message')
            if isinstance(raw_message, list):
                gateway_message = '; '.join(str(m) for m in raw_message)
            elif isinstance(raw_message, str):
                gateway_message = raw_message
        except ValueError:
            pass

        logger.error("ClickPesa push failed for order %s: %s %s", order.token, response.status_code, response.text)

        order.status = ExxabayGoOrder.STATUS_FAILED
        order.save(update_fields=['status'])

        SAFE_GATEWAY_ERROR_HINTS = ('insufficient', 'balance', 'phone', 'number', 'invalid')

        if gateway_message and any(hint in gateway_message.lower() for hint in SAFE_GATEWAY_ERROR_HINTS):
            buyer_message = gateway_message
        else:
            buyer_message = 'Payment request was rejected. Please try again.'

        return JsonResponse({'success': False, 'error': buyer_message}, status=400)

    return JsonResponse({'success': True, 'message': 'Payment prompt sent to your phone.'})


def order_payment_status(request, token):
    order = get_object_or_404(ExxabayGoOrder, token=token)

    if order.status in (ExxabayGoOrder.STATUS_PAID, ExxabayGoOrder.STATUS_FAILED):
        return JsonResponse({'status': order.status})

    if not order.order_reference:
        return JsonResponse({'status': order.status})

    auth_token = cp.generate_token()
    if not auth_token:
        return JsonResponse({'status': order.status})

    record = cp.query_payment_status(auth_token, order.order_reference)

    if record:
        gateway_status = (record.get('status') or '').upper()

        if gateway_status in ('SUCCESS', 'SETTLED'):
            order.status = ExxabayGoOrder.STATUS_PAID
            order.paid_at = timezone.now()
            order.save(update_fields=['status', 'paid_at'])
        elif gateway_status == 'FAILED':
            order.status = ExxabayGoOrder.STATUS_FAILED
            order.save(update_fields=['status'])
        # PROCESSING / PENDING → still in flight, leave as-is, frontend keeps polling

    return JsonResponse({'status': order.status})


from django.http import JsonResponse
from .utility import generate_paybill_number


def generate_billpay_views(request):
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Only POST requests are allowed."
        }, status=405)

    result = generate_paybill_number()

    if not result["success"]:
        return JsonResponse({
            "success": False,
            "message": "ClickPesa failed to generate the control number.",
            "clickpesa_response": result["data"]
        }, status=400)

    data = result["data"]

    return JsonResponse({
        "success": True,
        "billPayNumber": data["billPayNumber"]
    })

def pageView(request):
    return render(request, 'orders/control_no.html')

from .utility import generate_token
def token_generation_view (request):
    if request.method == "POST":
        token = generate_token()

    return JsonResponse ({
        "success": True,
        "token": token
    }, status=200)



# AZAMPAY PAYMENT VIEW
@login_required
def checkout_azam(request):

    if request.method != "POST":
        return redirect("orders:cart")

    phone = request.POST.get("phone")
    # provider = request.POST.get("provider", "")

    phone_number = _normalize_phone(
        phone or getattr(request.user, "phone_number", None)
    )

    if not phone_number:
        messages.error(
            request,
            "A valid phone number is required for mobile payment."
        )
        return redirect("users:edit_profile")

    with transaction.atomic():

        # 1. Lock cart
        cart = get_object_or_404(
            Cart.objects.select_for_update(),
            user=request.user,
        )

        items = list(
            cart.items
            .select_related("product")
            .select_for_update()
        )

        if not items:
            messages.error(request, "Your cart is empty.")
            return redirect("orders:cart")

        # 2. Validate stock
        total = Decimal("0.00")

        for item in items:

            product = item.product

            if not product.is_available:
                messages.error(
                    request,
                    f"'{product.name}' is no longer available."
                )
                return redirect("orders:cart")

            if item.quantity > product.stock:
                messages.error(
                    request,
                    f"Only {product.stock} unit(s) of "
                    f"'{product.name}' in stock."
                )
                return redirect("orders:cart")

            total += product.price * item.quantity

        # 3. Create order
        order = Order.objects.create(
            user=request.user,
            total_amount=total,
            status="pending",
        )

        # 4. Create order items
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price,
            )
            for item in items
        ])

        # 5. Create payment
        order_reference = generate_order_reference()

        payment = Payment.objects.create(
            order=order,
            amount=total,
            method="mobile_money",
            status="pending",
            transaction_id=order_reference
        )

        # 6. Initiate AzamPay payment
        from .utility import Payments, token_generation
        data = {
            "accountNumber": phone_number,
            "amount": int(total),
            "currency": "TZS",
            "externalId": order_reference,
            "provider": "Halopesa"
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token_generation()}",
        }

        print(headers)

        url = "https://checkout.azampay.co.tz/azampay/mno/checkout"

        # Creating payment instance
        payment_object = Payments(
            webhook=url,
            headers=headers,
            body=data,
        )

        # Call the request payment method to AzamPay
        azampay_response = payment_object.make_azam_pesa_post_request()

        if not azampay_response["success"]:
            transaction.set_rollback(True)

            messages.error(
                request,
                azampay_response["message"]
            )

            return redirect("orders:cart")

        # from main.messaging.service import MessagingClass
        # url = 'https://messaging-service.co.tz/api/sms/v2/text/single'
        # headers = {
        #     'Authorization': 'Bearer cedcce9becad866f59beac1fd5a235bc',
        #     'Content-Type': 'application/json',
        #     'Accept': 'application/json'
        # }
        # data = {
        #     "from": "MUST",
        #     "to": "255612350807",
        #     "text": f"Umelipa jumla ya {total} Tsh ",
        #     "flash": 0,
        #     "reference": "xaefcgt"
        # }

        # send_sms_instance = MessagingClass(url, headers, data)
        # send_sms_instance.send_sms()
        
    # Payment request was successfully sent
    return redirect(
        "orders:order_detail",
        order_id=order.id
    )