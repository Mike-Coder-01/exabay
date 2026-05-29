from django.urls import path

from . import views

app_name = "control_panel"

urlpatterns = [
    path("admin-panel/", views.admin_dashboard, name="dashboard"),
    path("admin-panel/payouts/", views.seller_payouts, name="seller_payouts"),
    path("admin-panel/payouts/sellers/<int:seller_id>/preview/", views.preview_seller_payout, name="preview_seller_payout"),
    path("admin-panel/payouts/<int:payout_id>/confirm/", views.confirm_seller_payout, name="confirm_seller_payout"),
    path("admin-panel/payouts/<int:payout_id>/refresh/", views.refresh_seller_payout_status, name="refresh_seller_payout_status"),
    path("admin-panel/sellers/<int:seller_id>/verify/", views.verify_seller, name="verify_seller"),
    path("admin-panel/sellers/<int:seller_id>/unverify/", views.unverify_seller, name="unverify_seller"),
    path("admin-panel/sellers/<int:seller_id>/reject/", views.reject_seller, name="reject_seller"),
    path("admin-panel/orders/<int:order_id>/status/", views.update_order_status, name="update_order_status"),
    path("admin-panel/users/<int:user_id>/contact/", views.contact_user, name="contact_user"),
]
