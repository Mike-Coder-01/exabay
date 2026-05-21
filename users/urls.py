from django.urls import path
from . import views

app_name = "users"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("complete-profile/", views.complete_profile_view, name="complete_profile"),
    path("logout/", views.logout_view, name="logout"),
    path('subscribe/', views.subscribe, name='subscribe'),
]
