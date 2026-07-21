from django.db import models
from django.contrib.auth.models import AbstractUser
from django.urls import reverse


class User(AbstractUser):
    email = models.EmailField(unique=True)
    is_seller = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=20)

    def get_absolute_url(self):
        return reverse(
            "users:login"
        )

    def __str__(self):
        return self.username


class SellerProfile(models.Model):

    REGIONAL_CHOICES = [
        ('ARU', 'Arusha'),
        ('DSM', 'Dar es salaam'),
        ('DOM', 'Dodoma'),
        ('GEITA', 'Geita'),
        ('IRINGA', 'Iringa'),
        ('KGR', 'Kagera'),
        ('KATAVI', 'Katavi'),
        ('KGM', 'Kigoma'),
        ('KLM', 'Kilimanjaro'),
        ('LINDI', 'Lindi'),
        ('MNYR', 'Manyara'),
        ('MARA', 'MARA'),
        ('MBY', 'Mbeya'),
        ('MORO', 'Morogoro'),
        ('MTWARA', 'Mtwara'),
        ('MWNZ', 'Mwanza'),
        ('NJOMBE', 'Njombe'),
        ('PWANI', 'Pwani'),
        ('RUKWA', 'Rukwa'),
        ('RVM', 'Ruvuma'),
        ('SHNYNG', 'Shinyanga'),
        ('SIMIYU', 'Simiyu'),
        ('SINGIDA', 'Singida'),
        ('SONGWE', 'Songwe'),
        ('TABORA', 'Tabora'),
        ('TANGA', 'Tanga'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    business_name = models.CharField(max_length=255, blank=True, null=True)
    located_region = models.CharField(max_length=225, default='DSM', choices=REGIONAL_CHOICES)

    # CORE TRUST FIELDS
    tin_number = models.CharField(max_length=50, blank=True, null=True)
    license_document = models.FileField(upload_to="documents/licenses/", blank=True, null=True)
    license_expiry_date = models.DateField(blank=True, null=True)

    # OPTIONAL
    vat_number = models.CharField(max_length=50, blank=True, null=True)
    tax_clearance_document = models.FileField(upload_to="documents/tax/", blank=True, null=True)
    vrn_number = models.CharField(max_length=50, blank=True, null=True)

    is_verified = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.business_name or self.user.username

    def is_profile_complete(self):
        return all([
            self.business_name,
            self.tin_number,
            self.license_document,
            self.license_expiry_date,
        ])


class Subscriber(models.Model):
    subscriber_email = models.EmailField(unique=True, null=True, blank=True)

    def __str__(self):
        return self.subscriber_email or ""


class SellerSettings(models.Model):
    MOBILE_PROVIDER_MPESA = "mpesa"
    MOBILE_PROVIDER_TIGO_PESA = "tigo_pesa"
    MOBILE_PROVIDER_AIRTEL_MONEY = "airtel_money"
    MOBILE_PROVIDER_HALOPESA = "halopesa"
    MOBILE_PROVIDER_OTHER = "other"

    MOBILE_PROVIDER_CHOICES = (
        (MOBILE_PROVIDER_MPESA, "M-Pesa"),
        (MOBILE_PROVIDER_TIGO_PESA, "Tigo Pesa"),
        (MOBILE_PROVIDER_AIRTEL_MONEY, "Airtel Money"),
        (MOBILE_PROVIDER_HALOPESA, "HaloPesa"),
        (MOBILE_PROVIDER_OTHER, "Other"),
    )

    seller = models.OneToOneField(
        SellerProfile,
        on_delete=models.CASCADE,
        related_name="settings",
    )

    store_display_name = models.CharField(max_length=255, blank=True)
    store_description = models.TextField(blank=True)
    business_location = models.CharField(max_length=255, blank=True)
    support_email = models.EmailField(blank=True)
    support_phone = models.CharField(max_length=20, blank=True)
    default_currency = models.CharField(max_length=10, default="Tsh")
    low_stock_threshold = models.PositiveIntegerField(default=5)

    notify_new_orders = models.BooleanField(default=True)
    notify_verification_updates = models.BooleanField(default=True)
    notify_low_stock = models.BooleanField(default=True)
    notify_admin_messages = models.BooleanField(default=True)

    mobile_money_provider = models.CharField(
        max_length=30,
        choices=MOBILE_PROVIDER_CHOICES,
        default=MOBILE_PROVIDER_MPESA,
    )
    payout_phone_number = models.CharField(max_length=20, blank=True)
    payout_account_name = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Seller settings"
        verbose_name_plural = "Seller settings"

    def __str__(self):
        return f"Settings for {self.seller}"