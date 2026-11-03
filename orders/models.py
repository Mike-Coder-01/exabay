from django.db import models
import uuid
from django.urls import reverse
from datetime import timedelta
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.db import models
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist, ValidationError

# Create your models here.
class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey('users.User', on_delete=models.CASCADE)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    order_control_number = models.CharField(max_length=100, null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    created_at = models.DateTimeField(auto_now_add=True)

    def get_absolute_url(self):
        return reverse(
            "orders:orders"
        )

    def __str__(self):
        return f"Order {self.id}"
    

class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )

    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField()

    # Customer-facing unit price at checkout
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # Seller's original unit price at checkout
    seller_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    fulfillment = models.ForeignKey(
        "orders.SellerFulfillment",
        on_delete=models.PROTECT,
        related_name="items",
        null=True,
        blank=True,
    )

    @property
    def subtotal(self):
        return self.price * self.quantity

    @property
    def seller_subtotal(self):
        if self.seller_price is None:
            return None
        return self.seller_price * self.quantity

    @property
    def platform_markup(self):
        if self.seller_price is None:
            return None
        return (self.price - self.seller_price) * self.quantity

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    

class Cart(models.Model):
    user = models.OneToOneField('users.User', on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cart - {self.user.username}"

    def get_total(self):
        return sum(item.product.price * item.quantity for item in self.items.all())
    

class CartItem(models.Model):
    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name='items'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['cart', 'product'],
                name='unique_cart_product'
            )
        ]

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"
    
    def get_total(self):
        return self.product.price * self.quantity

  
class SellerFulfillment(models.Model):

    DISPUTE_NONE = "none"
    DISPUTE_OPEN = "open"
    DISPUTE_RELEASE = "release"
    DISPUTE_REFUND = "refund"

    DISPUTE_CHOICES = [
        (DISPUTE_NONE, "No Dispute"),
        (DISPUTE_OPEN, "Dispute Open"),
        (DISPUTE_RELEASE, "Resolved - Release"),
        (DISPUTE_REFUND, "Resolved - Refund"),
    ]

    order = models.ForeignKey(
        "orders.Order",
        on_delete=models.PROTECT,
        related_name="seller_fulfillments",
    )

    seller = models.ForeignKey(
        "users.SellerProfile",
        on_delete=models.PROTECT,
        related_name="fulfillments",
    )

    shipped_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    release_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    buyer_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    dispute_status = models.CharField(
        max_length=20,
        choices=DISPUTE_CHOICES,
        default=DISPUTE_NONE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order", "seller"],
                name="unique_order_seller_fulfillment",
            ),
        ]

    @property
    def is_payment_paid(self):
        try:
            return self.order.payment.status == "paid"
        except ObjectDoesNotExist:
            return False

    def mark_shipped(self):
        """
        Start the 60-hour countdown when the seller
        marks their order portion as shipped.
        """

        if self.shipped_at is not None:
            raise ValidationError(
                "This fulfillment has already been shipped."
            )

        if not self.is_payment_paid:
            raise ValidationError(
                "Cannot ship an unpaid order."
            )

        if self.dispute_status != self.DISPUTE_NONE:
            raise ValidationError(
                "Cannot ship a fulfillment with a dispute decision."
            )

        self.shipped_at = timezone.now()
        self.release_at = self.shipped_at + timedelta(hours=60)

        self.save(
            update_fields=[
                "shipped_at",
                "release_at",
                "updated_at",
            ]
        )

    def confirm_received(self):
        """
        Record buyer confirmation.
        This makes the fulfillment eligible for payout
        if no dispute blocks it.
        """

        if not self.is_payment_paid:
            raise ValidationError(
                "Cannot confirm receipt of an unpaid order."
            )

        if self.shipped_at is None:
            raise ValidationError(
                "The seller has not shipped this order."
            )

        if self.dispute_status != self.DISPUTE_NONE:
            raise ValidationError(
                "Cannot confirm receipt while a dispute exists."
            )

        if self.buyer_confirmed_at is not None:
            raise ValidationError(
                "Receipt has already been confirmed."
            )

        self.buyer_confirmed_at = timezone.now()

        self.save(
            update_fields=[
                "buyer_confirmed_at",
                "updated_at",
            ]
        )

    @property
    def is_payout_eligible(self):
        """
        Payout is eligible when:
        1. Payment is successful.
        2. No active dispute or refund decision exists.
        3. Buyer confirmed receipt OR 60 hours expired,
           OR admin approved release after a dispute.
        """

        if not self.is_payment_paid:
            return False

        if self.dispute_status in (
            self.DISPUTE_OPEN,
            self.DISPUTE_REFUND,
        ):
            return False

        if self.dispute_status == self.DISPUTE_RELEASE:
            return True

        if self.shipped_at is None:
            return False

        if self.buyer_confirmed_at is not None:
            return True

        return (
            self.release_at is not None
            and timezone.now() >= self.release_at
        )

    def __str__(self):
        return (
            f"Order {self.order_id} - "
            f"Seller {self.seller_id}"
        )


class FulfillmentDispute(models.Model):

    fulfillment = models.OneToOneField(
        "orders.SellerFulfillment",
        on_delete=models.PROTECT,
        related_name="dispute",
    )

    reason = models.TextField()

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return (
            f"Dispute for fulfillment "
            f"#{self.fulfillment_id}"
        )


class Payment(models.Model):

    PAYMENT_METHODS = [
        ('cod', 'Cash on Delivery'),
        ('mobile_money', 'Mobile Money'),
    ]

    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ]

    order = models.OneToOneField('Order', on_delete=models.CASCADE)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    method = models.CharField(max_length=30, choices=PAYMENT_METHODS)

    status = models.CharField(max_length=30, choices=PAYMENT_STATUS, default='pending')

    transaction_id = models.CharField(max_length=255, blank=True, null=True)

    gateway_response = models.TextField(blank=True, null=True)   

    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"Payment for Order {self.order.id}"
    

class ExxabayGoOrder(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
    ]

    seller_profile = models.ForeignKey('users.SellerProfile', on_delete=models.CASCADE, null=True, blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    amount_to_be_paid = models.DecimalField(max_digits=12, decimal_places=2)
    order_reference = models.CharField(max_length=20, unique=True, blank=True, null=True)
    fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    buyer_phone_number = models.CharField(max_length=13)
    order_payment_link = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.order_payment_link:
            self.order_payment_link = f'/orders/order-payment/{self.token}/'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Order for {self.buyer_phone_number}'