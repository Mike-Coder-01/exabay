from django.contrib import admin
from . models import Payment, Order, OrderItem, Cart, CartItem, ExxabayGoOrder

# Register your models here.
admin.site.register(Payment)
admin.site.register(Order)
admin.site.register(OrderItem)
admin.site.register(Cart)
admin.site.register(CartItem)
admin.site.register(ExxabayGoOrder)