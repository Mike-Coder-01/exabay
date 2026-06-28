from django.urls import path
from . import views

app_name = 'main'

urlpatterns = [
    path('', views.home, name='home'),
    path("buyer-protection/", views.buyer_protection, name="buyer_protection"),
    path("seller-verification-policy/", views.seller_verification_policy, name="seller_verification_policy"),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),
    path("terms-of-service/", views.terms_of_service, name="terms_of_service"),
    path("report-seller/", views.report_seller, name="report_seller"),
    path("seller-guidelines/", views.seller_guidelines, name="seller_guidelines"),
]