from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.
class User(AbstractUser):
    email = models.EmailField(unique=True)
    is_seller = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.username
    
class SellerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    business_name = models.CharField(max_length=255, blank=True, null=True)

    # CORE TRUST FIELDS
    tin_number = models.CharField(max_length=50, blank=True, null=True)
    license_document = models.FileField(upload_to='documents/licenses/', blank=True, null=True)
    license_expiry_date = models.DateField(blank=True, null=True)

    # OPTIONAL
    vat_number = models.CharField(max_length=50, blank=True, null=True)
    tax_clearance_document = models.FileField(upload_to='documents/tax/', blank=True, null=True)
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
            self.license_expiry_date
        ])