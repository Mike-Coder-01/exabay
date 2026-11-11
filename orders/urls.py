from django.urls import path
from . import views

app_name = 'orders'

urlpatterns = [
    path('orders/', views.orderView, name='orders'),
    path('create_exxabay_go_order/', views.create_exxabay_go_order, name='exxabay_Go_Order'),
    path('order-payment/<uuid:token>/', views.order_payment_detail, name='order_payment_detail'),
    # path('order-payment/<uuid:token>/pay/', views.initiate_order_payment, name='initiate_order_payment'),
    # path('order-payment/<uuid:token>/status/', views.order_payment_status, name='order_payment_status'),
    path('checkout/', views.checkout_azam, name='checkout'),
    path("orders/<order_id>/confirm-received/", views.confirm_received, name="confirm_received"),
    # path('payment/callback/', views.payment_callback, name='payment_callback'),
    path("cart/", views.cart_view, name="cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/<int:item_id>/", views.update_cart_item, name="cart_update_item"),
    path("cart/remove/<int:item_id>/", views.remove_cart_item, name="cart_remove_item"),
    path("orders/<int:order_id>/", views.order_detail, name="order_detail"),
    path("seller_orders/", views.seller_orders, name="seller_orders"),
    path("seller/analytics/", views.seller_analytics, name="seller_analytics"),
    path("payment-status/<int:order_id>/", views.payment_status, name="payment_status"),
    path("fulfillments/<int:fulfillment_id>/confirm-received/", views.confirm_received, name="confirm_received"),
    path("fulfillments/<int:fulfillment_id>/report/",views.report_fulfillment_problem,name="report_fulfillment_problem"),
    path("fulfillments/<int:fulfillment_id>/mark-shipped/", views.mark_order_shipped, name="mark_order_shipped"),
    # path("payment-callback/", views.payment_callback, name="payment_callback"),
    # path("api/azampay/callback/", views.payment_callback, name="azampay-callback"),

    # path('generate_control_number/', views.token_generation_view, name='generate_control_number'),

    # path('page/', views.pageView, name='page'),
]