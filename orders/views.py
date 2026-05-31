from decimal import Decimal
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
from .models import Cart, CartItem, Order, OrderItem, Payment
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from users.decorators import seller_onboarding_required

logger = logging.getLogger(__name__)  
# __name__ will be 'orders.views' — covered by 'orders' logger above


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

# @login_required
# @transaction.atomic
# def checkout(request):
#     if request.method != "POST":
#         messages.error(request, "Invalid request.")
#         return redirect("orders:cart")

#     cart, created = Cart.objects.select_for_update().get_or_create(
#         user=request.user
#     )

#     cart_items = (
#         cart.items
#         .select_related("product", "product__seller")
#         .select_for_update()
#     )

#     if not cart_items.exists():
#         messages.error(request, "Your cart is empty.")
#         return redirect("orders:cart")

#     total_amount = Decimal("0.00")

#     for item in cart_items:
#         product = item.product

#         if not product.is_available:
#             messages.error(request, f"{product.name} is unavailable.")
#             return redirect("orders:cart")

#         if item.quantity > product.stock:
#             messages.error(request, f"Insufficient stock for {product.name}.")
#             return redirect("orders:cart")

#         total_amount += product.price * item.quantity

#     payment_success = True

#     if not payment_success:
#         messages.error(request, "Payment failed.")
#         return redirect("orders:cart")

#     order = Order.objects.create(
#         user=request.user,
#         total_amount=total_amount,
#         status="paid"
#     )

#     order_items = [
#         OrderItem(
#             order=order,
#             product=item.product,
#             quantity=item.quantity,
#             price=item.product.price
#         )
#         for item in cart_items
#     ]

#     OrderItem.objects.bulk_create(order_items)

#     for item in cart_items:
#         product = item.product
#         new_stock = product.stock - item.quantity

#         Product.objects.filter(pk=product.pk).update(
#             stock=F("stock") - item.quantity,
#             is_available=new_stock > 0
#         )

#     Payment.objects.create(
#         order=order,
#         amount=total_amount,
#         method="mobile_money",
#         status="paid",
#         transaction_id=str(uuid.uuid4())
#     )

#     cart.items.all().delete()

#     messages.success(request, "Checkout completed successfully.")
#     return redirect("orders:order_detail", order_id=order.id)

import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from orders.models import Cart, Order, OrderItem, Payment
from products.models import Product

from .services import (
    generate_order_reference,
    generate_token,
    initiate_ussd_push,
    preview_payment,
    validate_checksum,
)

logger = logging.getLogger(__name__)


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


# ══════════════════════════════════════════════════════════════════════════════
# CHECKOUT
# ══════════════════════════════════════════════════════════════════════════════

@login_required
def checkout(request):
    """
    POST-only. Flow:
      1. Validate cart & stock
      2. Create Order + OrderItems       (stock NOT deducted yet)
      3. Create pending Payment record
      4. Get ClickPesa token
      5. Preview  → validate phone / active channels
      6. USSD push → prompt customer's handset
      7. Redirect to order-detail page; stock deducted only on confirmed callback
    """
    if request.method != "POST":
        return redirect("orders:cart")

    phone_number = _normalize_phone(getattr(request.user, "phone_number", None))
    if not phone_number:
        messages.error(request, "A valid phone number is required for mobile payment.")
        return redirect("orders:cart")

    # ── 1. Lock cart rows ────────────────────────────────────────────────────
    with transaction.atomic():
        cart = get_object_or_404(
            Cart.objects.select_for_update(),
            user=request.user,
        )
        items = list(cart.items.select_related("product").select_for_update())

        if not items:
            messages.error(request, "Your cart is empty.")
            return redirect("orders:cart")

        total = Decimal("0.00")
        for item in items:
            product = item.product

            if not product.is_available:
                messages.error(request, f"'{product.name}' is no longer available.")
                return redirect("orders:cart")

            if item.quantity > product.stock:
                messages.error(
                    request,
                    f"Only {product.stock} unit(s) of '{product.name}' in stock.",
                )
                return redirect("orders:cart")

            total += product.price * item.quantity

        # ── 2. Create Order ──────────────────────────────────────────────────
        order = Order.objects.create(
            user=request.user,
            total_amount=total,
            status="pending",
        )

        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price,
            )
            for item in items
        ])

        # ── 3. Create Payment record ─────────────────────────────────────────
        order_reference = generate_order_reference()

        payment = Payment.objects.create(
            order=order,
            amount=total,
            method="mobile_money",
            status="pending",
            transaction_id=order_reference,
        )

    # ── 4. ClickPesa token ───────────────────────────────────────────────────
    # Outside the atomic block — network calls must not hold DB locks
    token = generate_token()
    if not token:
        logger.error("[CHECKOUT] Token generation failed. order=%s", order.id)
        _cancel_order(order, payment, "Token generation failed")
        messages.error(request, "Payment service unavailable. Please try again.")
        return redirect("orders:cart")

    # ── 5. Preview ───────────────────────────────────────────────────────────
    preview_resp = preview_payment(token, total, order_reference, phone_number)

    if preview_resp is None:
        logger.error("[CHECKOUT] Preview request failed. order=%s", order.id)
        _cancel_order(order, payment, "Preview request error")
        messages.error(request, "Could not reach payment gateway. Please try again.")
        return redirect("orders:cart")

    if preview_resp.status_code != 200:
        logger.error(
            "[CHECKOUT] Preview rejected. order=%s status=%s body=%s",
            order.id, preview_resp.status_code, preview_resp.text,
        )
        _cancel_order(order, payment, preview_resp.text)
        try:
            detail = preview_resp.json().get("message", "Payment preview failed.")
        except Exception:
            detail = "Payment preview failed."
        messages.error(request, detail)
        return redirect("orders:cart")

    active_methods = preview_resp.json().get("activeMethods", [])
    if not active_methods:
        logger.warning("[CHECKOUT] No active channels. order=%s phone=%s", order.id, phone_number)
        _cancel_order(order, payment, "No active payment channels")
        messages.error(request, "No payment channels available for your number right now.")
        return redirect("orders:cart")

    # ── 6. USSD push ─────────────────────────────────────────────────────────
    push_resp = initiate_ussd_push(token, total, order_reference, phone_number)

    if push_resp is None:
        logger.error("[CHECKOUT] USSD push request failed. order=%s", order.id)
        _cancel_order(order, payment, "USSD push request error")
        messages.error(request, "Could not send payment prompt. Please try again.")
        return redirect("orders:cart")

    if push_resp.status_code not in (200, 201):
        logger.error(
            "[CHECKOUT] USSD push rejected. order=%s status=%s body=%s",
            order.id, push_resp.status_code, push_resp.text,
        )
        _cancel_order(order, payment, push_resp.text)
        try:
            detail = push_resp.json().get("message", "Payment initiation failed.")
        except Exception:
            detail = "Payment initiation failed."
        messages.error(request, detail)
        return redirect("orders:cart")

    # ── 7. Save gateway response & redirect ──────────────────────────────────
    with transaction.atomic():
        if hasattr(payment, "gateway_response"):
            payment.gateway_response = push_resp.text
            payment.save(update_fields=["gateway_response"])

    logger.info("[CHECKOUT] USSD push sent. order=%s reference=%s", order.id, order_reference)
    messages.success(
        request,
        "A payment prompt has been sent to your phone. Please authorise it to complete your order.",
    )
    return redirect("orders:order_detail", order_id=order.id)



from .services import generate_token, query_payment_status

from django.utils import timezone
from datetime import timedelta

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
        logger.info("[POLL] result=%s", result)

        if result:
            clickpesa_status = result.get("status", "").upper()
            clickpesa_message = result.get("message", "")
            logger.info("[POLL] clickpesa_status=%s", clickpesa_status)

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
                logger.info("[POLL] PROCESSING age=%s", age)

                if age > timedelta(minutes=1):
                    logger.info("[POLL] PROCESSING timeout — marking as failed")
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
def payment_callback(request):
    """
    Handles two ClickPesa webhook events:
      • PAYMENT RECEIVED  → mark order paid, deduct stock, clear cart
      • PAYMENT FAILED    → mark order cancelled

    Security:
      - HMAC checksum validated before any DB writes
      - select_for_update prevents concurrent callback races
      - Stock deducted only here, never at checkout time
    """

    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed."},
            status=405,
        )

    # ── Parse JSON body ──────────────────────────────────────────────────────
    try:
        data = json.loads(request.body.decode("utf-8"))

    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("[CALLBACK] Malformed JSON body")

        return JsonResponse(
            {"error": "Invalid JSON."},
            status=400,
        )

    logger.info("[CALLBACK] payload=%s", data)

    # ── Extract inner payload ────────────────────────────────────────────────
    payload_data = data.get("data", {})

    if not isinstance(payload_data, dict):
        logger.warning("[CALLBACK] Missing or invalid data object")

        return JsonResponse(
            {"error": "Invalid payload structure."},
            status=400,
        )

    # ── Checksum validation ──────────────────────────────────────────────────
    # Remove checksum before recomputing signature
    received_checksum = payload_data.pop("checksum", None)

    if not received_checksum:
        logger.warning("[CALLBACK] Missing checksum")

        return JsonResponse(
            {"error": "Missing checksum."},
            status=400,
        )

    is_valid = validate_checksum(
        settings.CLICKPESA_CHECKSUM_KEY,
        payload_data,
        received_checksum,
    )

    if not is_valid:
        logger.warning(
            "[CALLBACK] Checksum mismatch. payload=%s",
            payload_data,
        )

        return JsonResponse(
            {"error": "Invalid checksum."},
            status=400,
        )

    # ── Extract event & order reference ─────────────────────────────────────
    event = data.get("event", "").upper()

    order_reference = payload_data.get("orderReference")

    logger.info(
        "[CALLBACK] event=%s reference=%s",
        event,
        order_reference,
    )

    if not order_reference:
        return JsonResponse(
            {"error": "Missing orderReference."},
            status=400,
        )

    # Ignore unrelated events
    if event not in ("PAYMENT RECEIVED", "PAYMENT FAILED"):
        logger.info(
            "[CALLBACK] Ignoring unhandled event=%s",
            event,
        )

        return JsonResponse({"ok": True})

    # ── Process payment safely ───────────────────────────────────────────────
    with transaction.atomic():

        try:
            payment = (
                Payment.objects
                .select_for_update()
                .select_related("order__user")
                .get(transaction_id=order_reference)
            )

        except Payment.DoesNotExist:
            logger.error(
                "[CALLBACK] Payment not found. reference=%s",
                order_reference,
            )

            return JsonResponse(
                {"error": "Payment not found."},
                status=404,
            )

        # ── Idempotency ──────────────────────────────────────────────────────
        if payment.status == "paid":
            logger.info(
                "[CALLBACK] Already paid. reference=%s",
                order_reference,
            )

            return JsonResponse({"ok": True})

        order = payment.order

        # ── PAYMENT RECEIVED ─────────────────────────────────────────────────
        if event == "PAYMENT RECEIVED":

            payment.status = "paid"
            payment.save(update_fields=["status"])

            order.status = "paid"
            order.save(update_fields=["status"])

            # Deduct stock atomically
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

                # Not enough stock
                if updated == 0:

                    logger.error(
                        "[CALLBACK] Insufficient stock. "
                        "product=%s order=%s",
                        item.product_id,
                        order.id,
                    )

                    raise InsufficientStockError(
                        item.product.name
                    )

            # Clear user's cart
            Cart.objects.filter(
                user=order.user
            ).delete()

            logger.info(
                "[CALLBACK] Order paid. order=%s",
                order.id,
            )

            return JsonResponse({"ok": True})

        # ── PAYMENT FAILED ───────────────────────────────────────────────────
        if event == "PAYMENT FAILED":

            payment.status = "failed"
            payment.save(update_fields=["status"])

            order.status = "cancelled"
            order.save(update_fields=["status"])

            logger.info(
                "[CALLBACK] Payment failed. order=%s",
                order.id,
            )

            return JsonResponse({"ok": False})

    # Fallback
    return JsonResponse({"ok": True})


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



from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils.dateparse import parse_date
from django.shortcuts import render

from products.models import Product
from users.decorators import seller_onboarding_required

from .models import OrderItem


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
