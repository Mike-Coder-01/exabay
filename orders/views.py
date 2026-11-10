import requests
import uuid
import logging
import json
from django.utils import timezone
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
from decimal import Decimal, InvalidOperation
from django.urls import reverse
from orders.models import SellerFulfillment
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


import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F
from django.shortcuts import redirect, get_object_or_404

from .models import (
    Cart,
    Order,
    OrderItem,
    Payment,
    SellerFulfillment,
)
from products.models import Product
from .utility import Payments, token_generation

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
    if phone.startswith("1"):
        return phone
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


# ============================================================================
# THIS BLOCK TO BE DELETED
# ============================================================================
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

# =======================================================================================
# END OF BLOCK TO BE DELETED
# =======================================================================================


@csrf_exempt
@require_POST
def payment_callback(request):
    """
    AzamPay callback with detailed diagnostic logging.
    """

    logger.info(
        "[AZAMPAY CALLBACK] ===== CALLBACK STARTED ====="
    )

    try:
        # 1. Parse callback JSON
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "[AZAMPAY CALLBACK] Invalid JSON body"
            )
            return JsonResponse(
                {"error": "Invalid JSON."}, status=400
            )

        if not isinstance(data, dict):
            logger.warning(
                "[AZAMPAY CALLBACK] JSON body is not an object"
            )
            return JsonResponse(
                {"error": "Invalid callback format."}, status=400
            )

        logger.info(
            "[AZAMPAY CALLBACK] JSON parsed successfully"
        )

        transaction_status = data.get("transactionstatus")
        utility_ref = data.get("utilityref")
        external_reference = data.get("externalreference")
        operator = data.get("operator")
        amount = data.get("amount")
        trans_id = data.get("transid")
        signature = data.get("signature")

        logger.info(
            "[AZAMPAY CALLBACK] Fields received: "
            "status=%s utilityref=%s transid=%s operator=%s",
            transaction_status,
            utility_ref,
            trans_id,
            operator,
        )

        # 2. Validate required fields
        required_fields = {
            "transactionstatus": transaction_status,
            "utilityref": utility_ref,
            "externalreference": external_reference,
            "operator": operator,
            "amount": amount,
            "signature": signature,
        }

        missing_fields = [
            field for field, value in required_fields.items()
            if value is None or value == ""
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

        # 3. Convert amount
        try:
            callback_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            logger.exception(
                "[AZAMPAY CALLBACK] Amount conversion failed"
            )
            return JsonResponse(
                {"error": "Invalid amount."}, status=400
            )

        if not callback_amount.is_finite() or callback_amount <= 0:
            logger.warning(
                "[AZAMPAY CALLBACK] Invalid numeric amount"
            )
            return JsonResponse(
                {"error": "Invalid amount."}, status=400
            )

        # 4. Obtain AzamPay public key
        logger.info(
            "[AZAMPAY CALLBACK] STEP 1: Fetching public key"
        )

        try:
            auth_token = token_generation()

            logger.info(
                "[AZAMPAY CALLBACK] Token generation completed"
            )

            public_key = get_azampay_public_key(
                settings.AZAMPAY_PUBLIC_KEY_URL,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                },
            )

        except Exception:
            logger.exception(
                "[AZAMPAY CALLBACK] FAILED at public-key/token retrieval"
            )
            raise

        if not public_key:
            logger.error(
                "[AZAMPAY CALLBACK] Public key is empty"
            )
            return JsonResponse(
                {"error": "Unable to verify callback."},
                status=500,
            )

        logger.info(
            "[AZAMPAY CALLBACK] Public key retrieved successfully"
        )

        # 5. Verify callback signature
        logger.info(
            "[AZAMPAY CALLBACK] STEP 2: Verifying signature"
        )

        try:
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
                    "[AZAMPAY CALLBACK] First signature check failed; "
                    "refreshing public key"
                )

                public_key = get_azampay_public_key(
                    settings.AZAMPAY_PUBLIC_KEY_URL,
                    headers={
                        "Authorization": (
                            f"Bearer {token_generation()}"
                        ),
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

        except Exception:
            logger.exception(
                "[AZAMPAY CALLBACK] FAILED during signature verification"
            )
            raise

        if not is_valid:
            logger.warning(
                "[AZAMPAY CALLBACK] Signature invalid; "
                "utilityref=%s",
                utility_ref,
            )
            return JsonResponse(
                {"error": "Invalid signature."}, status=400
            )

        logger.info(
            "[AZAMPAY CALLBACK] Signature verified successfully"
        )

        # 6. Find payment and process within a transaction
        logger.info(
            "[AZAMPAY CALLBACK] STEP 3: Looking up payment"
        )

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
                    "[AZAMPAY CALLBACK] Payment not found: %s",
                    utility_ref,
                )
                return JsonResponse(
                    {"error": "Payment not found."}, status=404
                )

            order = payment.order

            logger.info(
                "[AZAMPAY CALLBACK] Payment found: "
                "payment_id=%s order_id=%s",
                payment.id,
                order.id,
            )

            # 7. Verify amount
            if callback_amount != payment.amount:
                logger.error(
                    "[AZAMPAY CALLBACK] AMOUNT MISMATCH: "
                    "payment_id=%s expected=%s received=%s",
                    payment.id,
                    payment.amount,
                    callback_amount,
                )
                return JsonResponse(
                    {"error": "Payment amount mismatch."},
                    status=400,
                )

            # 8. Prevent duplicate processing
            if payment.status == "paid":
                logger.info(
                    "[AZAMPAY CALLBACK] Already processed: %s",
                    payment.id,
                )
                return JsonResponse({"ok": True})

            status = transaction_status.strip().lower()

            # 9. Successful payment
            if status == "success":
                logger.info(
                    "[AZAMPAY CALLBACK] STEP 4: Processing success"
                )

                # Deduct stock before marking the payment as paid.
                # Any raised exception rolls back the database transaction.
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
                            "[AZAMPAY CALLBACK] INSUFFICIENT STOCK: "
                            "product_id=%s order_id=%s quantity=%s",
                            item.product_id,
                            order.id,
                            item.quantity,
                        )
                        raise InsufficientStockError(
                            item.product.name
                        )

                payment.status = "paid"
                payment.gateway_response = json.dumps(data)
                payment.save(
                    update_fields=["status", "gateway_response"]
                )

                order.status = "paid"
                order.save(update_fields=["status"])

                Cart.objects.filter(user=order.user).delete()

                logger.info(
                    "[AZAMPAY CALLBACK] SUCCESS: "
                    "order_id=%s payment_id=%s transid=%s",
                    order.id,
                    payment.id,
                    trans_id,
                )

                return JsonResponse({"ok": True})

            # 10. Failed payment
            if status == "failed":
                logger.info(
                    "[AZAMPAY CALLBACK] Processing failed payment"
                )

                payment.status = "failed"
                payment.gateway_response = json.dumps(data)
                payment.save(
                    update_fields=["status", "gateway_response"]
                )

                order.status = "cancelled"
                order.save(update_fields=["status"])

                logger.info(
                    "[AZAMPAY CALLBACK] Payment marked failed: "
                    "order_id=%s payment_id=%s",
                    order.id,
                    payment.id,
                )

                return JsonResponse({"ok": True})

            logger.warning(
                "[AZAMPAY CALLBACK] Unknown transaction status: %s",
                transaction_status,
            )
            return JsonResponse(
                {"error": "Unhandled transaction status."},
                status=400,
            )

    except Exception:
        # Prints the exception type, message, and traceback.
        # Do not return the exception details to the payment gateway.
        logger.exception(
            "[AZAMPAY CALLBACK] UNHANDLED EXCEPTION — HTTP 500"
        )
        return JsonResponse(
            {"error": "Internal callback processing error."},
            status=500,
        )

    finally:
        logger.info(
            "[AZAMPAY CALLBACK] ===== CALLBACK FINISHED ====="
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



from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from orders.models import SellerFulfillment


@login_required
@require_POST
def confirm_received(request, fulfillment_id):

    with transaction.atomic():

        # 1. Lock the seller's fulfillment
        fulfillment = get_object_or_404(
            SellerFulfillment.objects
            .select_for_update()
            .select_related("order", "seller"),
            pk=fulfillment_id,
            order__user=request.user,
        )

        # 2. Confirm receipt using the model method
        try:
            fulfillment.confirm_received()

        except ValidationError as error:
            messages.error(
                request,
                "; ".join(error.messages),
            )

            return redirect(
                "orders:order_detail",
                order_id=fulfillment.order_id,
            )

        order_id = fulfillment.order_id

    # 3. Confirmation saved successfully
    messages.success(
        request,
        "You have confirmed receipt of this seller's "
        "products successfully.",
    )

    return redirect(
        "orders:order_detail",
        order_id=order_id,
    )



from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.http import require_POST
from orders.models import SellerFulfillment
from orders.models import (
    SellerFulfillment,
    FulfillmentDispute,
)
from control_panel.models import SellerPayout

@seller_onboarding_required
@require_POST
def mark_order_shipped(request, fulfillment_id):

    with transaction.atomic():

        fulfillment = get_object_or_404(
            SellerFulfillment.objects
            .select_for_update()
            .select_related("order", "seller"),
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
            return redirect("orders:seller_orders")

    messages.success(
        request,
        "Order marked as shipped successfully. "
        "The 60-hour payout countdown has started.",
    )

    return redirect("orders:seller_orders")


from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from orders.models import (
    SellerFulfillment,
    FulfillmentDispute,
)



@login_required
@require_http_methods(["GET", "POST"])
def report_fulfillment_problem(request, fulfillment_id):

    # --------------------------------------------------
    # STEP 1: Retrieve the buyer's fulfillment
    # --------------------------------------------------

    fulfillment = get_object_or_404(
        SellerFulfillment.objects.select_related(
            "order",
            "seller",
        ),
        pk=fulfillment_id,
        order__user=request.user,
    )

    if request.method == "POST":

        reason = request.POST.get("reason", "").strip()

        if len(reason) < 10:
            messages.error(
                request,
                "Please describe the problem in at least 10 characters."
            )
            return redirect(
                "orders:report_fulfillment_problem",
                fulfillment_id=fulfillment.id,
            )

        if len(reason) > 5000:
            messages.error(
                request,
                "Your description cannot exceed 5000 characters."
            )
            return redirect(
                "orders:report_fulfillment_problem",
                fulfillment_id=fulfillment.id,
            )

        # --------------------------------------------------
        # STEP 2: Lock seller and fulfillment
        # --------------------------------------------------

        with transaction.atomic():

            # Identify the seller without locking fulfillment.
            fulfillment_info = get_object_or_404(
                SellerFulfillment.objects.only(
                    "id",
                    "seller_id",
                    "order_id",
                ),
                pk=fulfillment_id,
                order__user=request.user,
            )

            # Lock seller first, matching payout confirmation.
            SellerProfile.objects.select_for_update().get(
                pk=fulfillment_info.seller_id
            )

            # Lock the fulfillment after locking seller.
            fulfillment = get_object_or_404(
                SellerFulfillment.objects
                .select_for_update()
                .select_related("order"),
                pk=fulfillment_id,
                order__user=request.user,
            )

            # --------------------------------------------------
            # STEP 3: Validate payment and shipment
            # --------------------------------------------------

            if not fulfillment.is_payment_paid:
                messages.error(
                    request,
                    "You cannot report a problem for an unpaid order."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            if fulfillment.shipped_at is None:
                messages.error(
                    request,
                    "This fulfillment has not been shipped."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            # --------------------------------------------------
            # STEP 4: Check existing dispute or confirmation
            # --------------------------------------------------

            if fulfillment.dispute_status != "none":
                messages.error(
                    request,
                    "This fulfillment already has a dispute "
                    "or resolution recorded."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            if fulfillment.buyer_confirmed_at is not None:
                messages.error(
                    request,
                    "This fulfillment has already been "
                    "confirmed received."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            # --------------------------------------------------
            # STEP 5: Enforce the 60-hour dispute deadline
            # --------------------------------------------------

            if (
                fulfillment.release_at is None
                or timezone.now() >= fulfillment.release_at
            ):
                messages.error(
                    request,
                    "The 60-hour dispute period has expired. "
                    "You can no longer open a dispute "
                    "for this delivery."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            # --------------------------------------------------
            # STEP 6: Prevent disputes after payout reservation
            # --------------------------------------------------

            active_payout_exists = SellerPayout.objects.filter(
                order_items__fulfillment=fulfillment,
                status__in=[
                    SellerPayout.STATUS_AUTHORIZED,
                    SellerPayout.STATUS_PENDING,
                    SellerPayout.STATUS_PROCESSING,
                    SellerPayout.STATUS_SUCCESS,
                    SellerPayout.STATUS_REFUNDED,
                ],
            ).exists()

            if active_payout_exists:
                messages.error(
                    request,
                    "A payout has already been reserved "
                    "or processed for this delivery. "
                    "You cannot open a new dispute."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            # --------------------------------------------------
            # STEP 7: Prevent duplicate disputes
            # --------------------------------------------------

            if FulfillmentDispute.objects.filter(
                fulfillment=fulfillment
            ).exists():
                messages.error(
                    request,
                    "A dispute already exists for this fulfillment."
                )
                return redirect(
                    "orders:order_detail",
                    order_id=fulfillment.order_id,
                )

            # --------------------------------------------------
            # STEP 8: Create dispute and block payout
            # --------------------------------------------------

            FulfillmentDispute.objects.create(
                fulfillment=fulfillment,
                reason=reason,
            )

            fulfillment.dispute_status = "open"

            fulfillment.save(
                update_fields=[
                    "dispute_status",
                    "updated_at",
                ]
            )

        # --------------------------------------------------
        # STEP 9: Confirm submission
        # --------------------------------------------------

        messages.success(
            request,
            "Your report has been submitted successfully. "
            "The seller's payout has been placed on hold "
            "while Exxabay reviews the issue."
        )

        return redirect(
            "orders:order_detail",
            order_id=fulfillment.order_id,
        )

    # --------------------------------------------------
    # STEP 10: Display the report form
    # --------------------------------------------------

    return render(
        request,
        "orders/report_problem.html",
        {
            "fulfillment": fulfillment,
        },
    )


@seller_onboarding_required
def seller_orders(request):
    seller = request.user.sellerprofile
    status = request.GET.get("status", "all")
    page_number = request.GET.get("page")

    status_filters = [
        ("all", "All orders"),
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("shipped", "Shipped"),
        ("received", "Received"),
        ("cancelled", "Cancelled"),
    ]

    valid_statuses = {value for value, _ in status_filters}

    if status not in valid_statuses:
        status = "all"

    # Seller earnings, excluding Exxabay's markup
    seller_line_total = ExpressionWrapper(
        F("quantity") * F("seller_price"),
        output_field=DecimalField(
            max_digits=14,
            decimal_places=2,
        ),
    )

    seller_items = (
        OrderItem.objects
        .filter(product__seller=seller)
        .select_related(
            "order",
            "order__user",
            "order__payment",
            "fulfillment",
            "product",
            "product__category",
            "product__seller",
        )
        .prefetch_related("product__images")
        .annotate(line_total=seller_line_total)
        .order_by("-order_id", "-id")
    )

    # Filter using seller fulfillment where applicable
    if status == "pending":
        seller_items = seller_items.filter(
            order__payment__status="pending"
        )

    elif status == "paid":
        seller_items = seller_items.filter(
            order__payment__status="paid",
            fulfillment__shipped_at__isnull=True,
            fulfillment__dispute_status="none",
        )

    elif status == "shipped":
        seller_items = seller_items.filter(
            fulfillment__shipped_at__isnull=False,
            fulfillment__buyer_confirmed_at__isnull=True,
        )

    elif status == "received":
        seller_items = seller_items.filter(
            fulfillment__buyer_confirmed_at__isnull=False,
        )

    elif status == "cancelled":
        seller_items = seller_items.filter(
            order__status="cancelled"
        )

    paginator = Paginator(seller_items, 10)
    page_obj = paginator.get_page(page_number)

    base_items = OrderItem.objects.filter(
        product__seller=seller
    )

    summary = base_items.aggregate(
        total_revenue=Sum(
            seller_line_total,
            filter=Q(order__payment__status="paid"),
        ),
        total_units=Sum("quantity"),
        total_orders=Count("order", distinct=True),
        pending_orders=Count(
            "order",
            filter=Q(order__payment__status="pending"),
            distinct=True,
        ),
        paid_orders=Count(
            "order",
            filter=Q(order__payment__status="paid"),
            distinct=True,
        ),
        completed_orders=Count(
            "order",
            filter=Q(
                fulfillment__buyer_confirmed_at__isnull=False
            ),
            distinct=True,
        ),
    )

    for key in summary:
        summary[key] = summary[key] or 0

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




# ===============================================================================
# THESE IS FOR EXXABAYGO
# ==============================================================================
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

# PAYMENT PROCESSING FOR EXXABAYGO ORDER
# GOES HERE
# =========================================================================================



@login_required
def checkout_azam(request):

    ALLOWED_PROVIDERS = {
    "Mpesa",
    "Tigo",
    "Airtel",
    "Halopesa",
    }
    # Only allow POST requests
    if request.method != "POST":
        return redirect("orders:cart")

    # 1. Validate customer's phone number
    phone = request.POST.get("phone")
    # 2. Get selected provider
    provider = request.POST.get(
        "provider", ""
    ).strip()

    # 3. Validate provider
    if provider not in ALLOWED_PROVIDERS:
        messages.error(
            request,
            "Please select a valid mobile money provider."
        )
        return redirect("orders:cart")

    # 4. Get payment phone number
    phone = request.POST.get(
        "phone", ""
    ).strip()

    # 5. Normalize phone number
    phone_number = _normalize_phone(phone)

    # 6. Validate phone number
    if not phone_number:
        messages.error(
            request,
            "Please enter a valid mobile money phone number."
        )
        return redirect("orders:cart")

    # 7. Create pending order inside a database transaction
    with transaction.atomic():

        cart = get_object_or_404(
            Cart.objects.select_for_update(),
            user=request.user,
        )

        items = list(
            cart.items
            .select_for_update()
            .order_by("pk")
        )

        if not items:
            messages.error(request, "Your cart is empty.")
            return redirect("orders:cart")

        # Lock the products in a consistent order
        product_ids = [item.product_id for item in items]

        products = {
            product.pk: product
            for product in (
                Product.objects
                .select_for_update()
                .filter(pk__in=product_ids)
                .order_by("pk")
            )
        }

        # 8. Validate products and calculate total
        total = Decimal("0.00")

        for item in items:

            product = products.get(item.product_id)

            if product is None or not product.is_available:
                messages.error(
                    request,
                    "One of your products is no longer available."
                )
                return redirect("orders:cart")

            if item.quantity > product.stock:
                messages.error(
                    request,
                    f"Only {product.stock} unit(s) of "
                    f"'{product.name}' are available."
                )
                return redirect("orders:cart")

            if (
                product.seller_price is None
                or product.seller_price <= 0
                or product.price <= 0
            ):
                messages.error(
                    request,
                    f"'{product.name}' has invalid pricing."
                )
                return redirect("orders:cart")

            total += product.price * item.quantity

        # 9. Create one order
        order = Order.objects.create(
            user=request.user,
            total_amount=total,
            status="pending",
        )

        # 10. Create one fulfillment per seller
        seller_fulfillments = {}

        for item in items:

            product = products[item.product_id]
            seller_id = product.seller_id

            if seller_id not in seller_fulfillments:

                fulfillment = SellerFulfillment.objects.create(
                    order=order,
                    seller_id=seller_id,
                )

                seller_fulfillments[seller_id] = fulfillment

            fulfillment = seller_fulfillments[seller_id]

            # Save prices at checkout
            OrderItem.objects.create(
                order=order,
                product=product,
                fulfillment=fulfillment,
                quantity=item.quantity,
                price=product.price,
                seller_price=product.seller_price,
            )

        # 11. Create pending payment
        order_reference = generate_order_reference()

        payment = Payment.objects.create(
            order=order,
            amount=total,
            method="mobile_money",
            status="pending",
            transaction_id=order_reference,
        )

    # Database transaction has now committed.
    # The callback can find the pending payment.

    # 12. Prepare AzamPay collection request
    data = {
        "accountNumber": phone_number,
        "amount": int(total),
        "currency": "TZS",
        "externalId": order_reference,
        "provider": provider,
    }

    try:
        token = token_generation()

        if not token:
            raise ValueError("AzamPay authentication failed.")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        payment_object = Payments(
            webhook="https://checkout.azampay.co.tz/azampay/mno/checkout",
            headers=headers,
            body=data,
        )

        # 13. Send payment request
        azampay_response = (
            payment_object.make_azam_pesa_post_request()
        )

        if not azampay_response.get("success"):
            logger.warning(
                "AzamPay checkout initiation unsuccessful. "
                "Order=%s Response=%s",
                order.id,
                azampay_response,
            )

            messages.warning(
                request,
                "Payment could not be initiated or its status "
                "could not be confirmed. Please check your order "
                "before trying again.",
            )

            return redirect(
                "orders:order_detail",
                order_id=order.id,
            )

    except Exception:
        logger.exception(
            "AzamPay initiation error for order %s",
            order.id,
        )

        messages.warning(
            request,
            "We could not confirm whether the payment request "
            "was sent. Please check your order status before "
            "attempting another payment.",
        )

        return redirect(
            "orders:order_detail",
            order_id=order.id,
        )

    # 14. Payment request accepted, but not yet paid
    messages.success(
        request,
        "Payment request sent. Complete the payment "
        "on your phone.",
    )

    return redirect(
        "orders:order_detail",
        order_id=order.id,
    )
