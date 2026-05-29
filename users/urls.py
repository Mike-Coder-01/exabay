from django.urls import path
from . import views

app_name = "users"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("complete-profile/", views.complete_profile_view, name="complete_profile"),
    path("dashboard/", views.buyer_dashboard, name="buyer_dashboard"),
    path("logout/", views.logout_view, name="logout"),
    path('subscribe/', views.subscribe, name='subscribe'),
    path("edit_profile/", views.edit_profile_view, name='edit_profile'),
    path("settings/", views.seller_settings_view, name="seller_settings"),
    path("notifications/", views.notifications_view, name="notifications"),
    path("notifications/<int:notification_id>/read/", views.mark_notification_read, name="mark_notification_read"),
    path("notifications/read-all/", views.mark_all_notifications_read, name="mark_all_notifications_read"),
]
