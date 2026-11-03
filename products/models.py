from django.db import models
from decimal import Decimal
from django.urls import reverse
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError

# Create your models here.
class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    seller = models.ForeignKey('users.SellerProfile', on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')

    name = models.CharField(max_length=255)
    description = models.TextField()

    price = models.DecimalField(max_digits=10, decimal_places=2)
    seller_price = models.DecimalField(
    max_digits=10,
    decimal_places=2,
    null=True,
    blank=True,
)
    stock = models.PositiveIntegerField()

    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse(
            "products:products"
        )
    
    def save(self, *args, **kwargs):

        # 1. Check seller verification when creating a product
        if self._state.adding and not self.seller.is_verified:
            raise ValidationError(
                "Seller is not verified and cannot create products."
            )

        # 2. New products must have a seller price
        if self._state.adding and self.seller_price is None:
            raise ValidationError(
                "Seller price is required."
            )

        # 3. Validate and calculate prices
        if self.seller_price is not None:

            seller_price = Decimal(str(self.seller_price))

            if not seller_price.is_finite() or seller_price <= 0:
                raise ValidationError(
                    "Seller price must be greater than zero."
                )

            # Store seller price to two decimal places
            self.seller_price = seller_price.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            # Calculate buyer-facing price
            self.price = (
                self.seller_price * Decimal("1.10")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP
            )

            # Ensure both fields are saved when using update_fields
            if kwargs.get("update_fields") is not None:
                update_fields = set(kwargs["update_fields"])

                if update_fields and (
                    "seller_price" in update_fields
                    or "price" in update_fields
                ):
                    update_fields.update({"seller_price", "price"})
                    kwargs["update_fields"] = update_fields

        super().save(*args, **kwargs)



class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')

    def __str__(self):
        return f"Image for {self.product.name}"
    
    
class ProductSpecification(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='specs')
    key = models.CharField(max_length=100)
    value = models.CharField(max_length=255)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'key'],
                name='unique_product_spec_key'
            )
        ]