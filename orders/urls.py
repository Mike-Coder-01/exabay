from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('orders/', views.orderView, name='orders'),
    path('checkout/', views.checkout, name='checkout'),
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/<int:item_id>/", views.update_cart_item, name="cart_update_item"),
    path("cart/remove/<int:item_id>/", views.remove_cart_item, name="cart_remove_item"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),

]