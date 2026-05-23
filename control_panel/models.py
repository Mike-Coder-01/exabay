from django.conf import settings
from django.db import models
from django.utils import timezone


class SellerVerificationReview(models.Model):
    STATUS_PENDING = "pending"
    STATUS_VERIFIED = "verified"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_REJECTED, "Rejected"),
    )

    seller = models.OneToOneField(
        "users.SellerProfile",
        on_delete=models.CASCADE,
        related_name="verification_review",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="seller_reviews_completed",
    )
    reviewed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def mark_verified(self, admin_user, reason=""):
        self.status = self.STATUS_VERIFIED
        self.reason = reason
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.seller.is_verified = True
        self.seller.save(update_fields=["is_verified"])
        self.save(update_fields=["status", "reason", "reviewed_by", "reviewed_at", "updated_at"])

    def mark_rejected(self, admin_user, reason):
        self.status = self.STATUS_REJECTED
        self.reason = reason
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.seller.is_verified = False
        self.seller.save(update_fields=["is_verified"])
        self.save(update_fields=["status", "reason", "reviewed_by", "reviewed_at", "updated_at"])

    def mark_unverified(self, admin_user, reason):
        self.status = self.STATUS_PENDING
        self.reason = reason
        self.reviewed_by = admin_user
        self.reviewed_at = timezone.now()
        self.seller.is_verified = False
        self.seller.save(update_fields=["is_verified"])
        self.save(update_fields=["status", "reason", "reviewed_by", "reviewed_at", "updated_at"])

    def __str__(self):
        return f"{self.seller} - {self.get_status_display()}"


class AdminNotification(models.Model):
    TYPE_SELLER_VERIFIED = "seller_verified"
    TYPE_SELLER_UNVERIFIED = "seller_unverified"
    TYPE_SELLER_REJECTED = "seller_rejected"
    TYPE_SELLER_MESSAGE = "seller_message"
    TYPE_BUYER_MESSAGE = "buyer_message"
    TYPE_ORDER_FOLLOW_UP = "order_follow_up"

    TYPE_CHOICES = (
        (TYPE_SELLER_VERIFIED, "Seller verified"),
        (TYPE_SELLER_UNVERIFIED, "Seller unverified"),
        (TYPE_SELLER_REJECTED, "Seller rejected"),
        (TYPE_SELLER_MESSAGE, "Seller message"),
        (TYPE_BUYER_MESSAGE, "Buyer message"),
        (TYPE_ORDER_FOLLOW_UP, "Order follow-up"),
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="admin_notifications_sent",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_notifications_received",
    )
    notification_type = models.CharField(max_length=40, choices=TYPE_CHOICES)
    subject = models.CharField(max_length=255)
    message = models.TextField()
    related_seller = models.ForeignKey(
        "users.SellerProfile",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="admin_notifications",
    )
    related_order = models.ForeignKey(
        "orders.Order",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="admin_notifications",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.subject