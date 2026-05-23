from django.urls import path

from . import views

app_name = "control_panel"

urlpatterns = [
    path("admin-panel/", views.admin_dashboard, name="dashboard"),
    path("admin-panel/sellers/<int:seller_id>/verify/", views.verify_seller, name="verify_seller"),
    path("admin-panel/sellers/<int:seller_id>/unverify/", views.unverify_seller, name="unverify_seller"),
    path("admin-panel/sellers/<int:seller_id>/reject/", views.reject_seller, name="reject_seller"),
    path("admin-panel/orders/<int:order_id>/status/", views.update_order_status, name="update_order_status"),
    path("admin-panel/users/<int:user_id>/contact/", views.contact_user, name="contact_user"),
]