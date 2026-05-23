from decimal import Decimal
import uuid
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
        return redirect("orders:product_detail", pk=product.id)

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
    cart, created = Cart.objects.get_or_create(user=request.user)

    item = get_object_or_404(
        CartItem.objects.select_related("product"),
        pk=item_id,
        cart=cart
    )

    try:
        quantity = int(request.POST.get("quantity", item.quantity))
    except ValueError:
        quantity = item.quantity

    quantity = max(1, quantity)

    if quantity > item.product.stock:
        return JsonResponse({
            "success": False,
            "message": "Not enough stock available."
        }, status=400)

    item.quantity = quantity
    item.save(update_fields=["quantity"])

    cart_total = sum(i.product.price * i.quantity for i in cart.items.select_related("product"))

    return JsonResponse({
        "success": True,
        "quantity": item.quantity,
        "item_subtotal": str(item.product.price * item.quantity),
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
@transaction.atomic
def checkout(request):
    if request.method != "POST":
        messages.error(request, "Invalid request.")
        return redirect("orders:cart")

    cart, created = Cart.objects.select_for_update().get_or_create(
        user=request.user
    )

    cart_items = (
        cart.items
        .select_related("product", "product__seller")
        .select_for_update()
    )

    if not cart_items.exists():
        messages.error(request, "Your cart is empty.")
        return redirect("orders:cart")

    total_amount = Decimal("0.00")

    for item in cart_items:
        product = item.product

        if not product.is_available:
            messages.error(request, f"{product.name} is unavailable.")
            return redirect("orders:cart")

        if item.quantity > product.stock:
            messages.error(request, f"Insufficient stock for {product.name}.")
            return redirect("orders:cart")

        total_amount += product.price * item.quantity

    payment_success = True

    if not payment_success:
        messages.error(request, "Payment failed.")
        return redirect("orders:cart")

    order = Order.objects.create(
        user=request.user,
        total_amount=total_amount,
        status="paid"
    )

    order_items = [
        OrderItem(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price
        )
        for item in cart_items
    ]

    OrderItem.objects.bulk_create(order_items)

    for item in cart_items:
        product = item.product
        new_stock = product.stock - item.quantity

        Product.objects.filter(pk=product.pk).update(
            stock=F("stock") - item.quantity,
            is_available=new_stock > 0
        )

    Payment.objects.create(
        order=order,
        amount=total_amount,
        method="mobile_money",
        status="paid",
        transaction_id=str(uuid.uuid4())
    )

    cart.items.all().delete()

    messages.success(request, "Checkout completed successfully.")
    return redirect("orders:order_detail", order_id=order.id)


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