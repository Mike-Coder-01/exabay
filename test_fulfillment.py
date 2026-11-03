
from django.db import transaction
from orders.models import Order, OrderItem, SellerFulfillment
from products.models import Product
from users.models import User

product = Product.objects.get(name="Lenovo")
buyer = User.objects.filter(is_superuser=True).first()

if buyer is None:
    raise ValueError("No test buyer found.")

# Test inside a transaction that will be rolled back.
# This creates no permanent test records.
with transaction.atomic():

    order = Order.objects.create(
        user=buyer,
        total_amount=product.price,
        status="pending",
    )

    fulfillment = SellerFulfillment.objects.create(
        order=order,
        seller=product.seller,
    )

    item = OrderItem.objects.create(
        order=order,
        product=product,
        fulfillment=fulfillment,
        quantity=1,
        price=product.price,
        seller_price=product.seller_price,
    )

    print("Order:", order.id)
    print("Fulfillments:", order.seller_fulfillments.count())
    print("Seller price:", item.seller_price)
    print("Customer price:", item.price)
    print("Fulfillment ID:", item.fulfillment_id)

    # Roll back the test records.
    transaction.set_rollback(True)

print("Test completed. No test records were saved.")
