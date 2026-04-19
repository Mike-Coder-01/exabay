from .models import Order, OrderItem
from products.models import Product
from django.db import transaction

@transaction.atomic
def checkout_cart(cart):
    # 1. Create order
    order = Order.objects.create(
        user=cart.user,
        total_amount=0
    )

    total = 0

    # 2. Convert cart items → order items
    for item in cart.items.select_related('product'):
        product = item.product

        # stock check
        if product.stock < item.quantity:
            raise Exception(f"Not enough stock for {product.name}")

        # reduce stock
        product.stock -= item.quantity
        product.save()

        # create order item
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=item.quantity,
            price=product.price
        )

        total += product.price * item.quantity

    # 3. update total
    order.total_amount = total
    order.save()

    # 4. clear cart
    cart.items.all().delete()

    return order