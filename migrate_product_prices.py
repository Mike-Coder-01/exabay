
from decimal import Decimal
from django.db import transaction
from products.models import Product

product_ids = [2, 3, 4, 7, 8, 9, 10]

with transaction.atomic():
    products = list(
        Product.objects.select_for_update()
        .filter(
            id__in=product_ids,
            seller_price__isnull=True
        )
        .order_by("id")
    )

    if len(products) != 7:
        raise ValueError(
            f"Expected 7 products, found {len(products)}. "
            "No changes were saved."
        )

    for product in products:
        original_price = Decimal(product.price)

        product.seller_price = original_price
        product.save(update_fields=["seller_price"])

        print(
            product.name,
            "| Seller:", product.seller_price,
            "| Customer:", product.price
        )

print("Migration completed successfully!")
