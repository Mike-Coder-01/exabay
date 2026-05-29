from django.db import models

# Create your models here.
class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey('users.User', on_delete=models.CASCADE)

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Order {self.id}"
    
class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE)

    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.price * self.quantity


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

    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')

    transaction_id = models.CharField(max_length=255, blank=True, null=True)

    gateway_response = models.TextField(blank=True, null=True)   # ← ADD THIS

    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"Payment for Order {self.order.id}"
    
