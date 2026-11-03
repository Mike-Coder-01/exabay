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


class SellerPayout(models.Model):
    STATUS_PREVIEWED = "previewed"
    STATUS_AUTHORIZED = "authorized"
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_REVERSED = "reversed"
    STATUS_REFUNDED = "refunded"

    STATUS_CHOICES = (
        (STATUS_PREVIEWED, "Previewed"),
        (STATUS_AUTHORIZED, "Authorized"),
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REVERSED, "Reversed"),
        (STATUS_REFUNDED, "Refunded"),
    )

    seller = models.ForeignKey(
        "users.SellerProfile",
        on_delete=models.PROTECT,
        related_name="payouts",
    )
    order_items = models.ManyToManyField(
        "orders.OrderItem",
        related_name="seller_payouts",
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="seller_payouts_created",
    )
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="TZS")
    phone_number = models.CharField(max_length=30)
    account_name = models.CharField(max_length=255, blank=True)
    order_reference = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_PREVIEWED)
    channel_provider = models.CharField(max_length=100, blank=True)
    clickpesa_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    clickpesa_total_deducted = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    preview_response = models.JSONField(blank=True, null=True)
    gateway_response = models.JSONField(blank=True, null=True)
    failure_reason = models.TextField(blank=True)
    initiated_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # AzamPay transaction identifiers
    pg_reference_id = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    fsp_reference_id = models.CharField(
        max_length=100,
        blank=True,
    )

    # Last verified transaction status
    gateway_verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.seller} payout {self.order_reference}"




class SellerPayoutReservation(models.Model):

    payout = models.ForeignKey(
        "SellerPayout",
        on_delete=models.PROTECT,
        related_name="reservations",
    )

    order_item = models.OneToOneField(
        "orders.OrderItem",
        on_delete=models.PROTECT,
        related_name="payout_reservation",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        verbose_name = "Seller Payout Reservation"
        verbose_name_plural = "Seller Payout Reservations"

    def __str__(self):
        return (
            f"Order item #{self.order_item_id} "
            f"reserved for payout #{self.payout_id}"
        )


from django.conf import settings
from django.db import models


class SellerPayoutInvestigation(models.Model):

    OUTCOME_UNKNOWN = "unknown"
    OUTCOME_CONFIRMED_PAID = "confirmed_paid"
    OUTCOME_CONFIRMED_FAILED = "confirmed_failed"

    OUTCOME_CHOICES = [
        (OUTCOME_UNKNOWN, "Outcome unknown"),
        (OUTCOME_CONFIRMED_PAID, "Confirmed paid"),
        (OUTCOME_CONFIRMED_FAILED, "Confirmed failed"),
    ]

    payout = models.ForeignKey(
        "SellerPayout",
        on_delete=models.PROTECT,
        related_name="investigations",
    )

    investigated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_investigations",
    )

    reason = models.TextField()

    provider_reference = models.CharField(
        max_length=150,
        blank=True,
    )

    findings = models.TextField(
        blank=True,
    )

    outcome = models.CharField(
        max_length=30,
        choices=OUTCOME_CHOICES,
        default=OUTCOME_UNKNOWN,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Seller payout investigation"
        verbose_name_plural = "Seller payout investigations"

    def __str__(self):
        return (
            f"Investigation #{self.pk} - "
            f"{self.payout.order_reference} - "
            f"{self.get_outcome_display()}"
        )



from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class SellerPayoutResolution(models.Model):

    # Proposed payment outcomes
    OUTCOME_PAID = "confirmed_paid"
    OUTCOME_FAILED = "confirmed_failed"

    OUTCOME_CHOICES = [
        (OUTCOME_PAID, "Confirmed paid"),
        (OUTCOME_FAILED, "Confirmed failed"),
    ]

    # Approval statuses
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    payout = models.ForeignKey(
        "SellerPayout",
        on_delete=models.PROTECT,
        related_name="resolutions",
    )

    investigation = models.ForeignKey(
        "SellerPayoutInvestigation",
        on_delete=models.PROTECT,
        related_name="resolutions",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_payout_resolutions",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_payout_resolutions",
        null=True,
        blank=True,
    )

    proposed_outcome = models.CharField(
        max_length=30,
        choices=OUTCOME_CHOICES,
    )

    provider_reference = models.CharField(
        max_length=150,
    )

    evidence = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    approval_notes = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    decided_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

        verbose_name = "Seller payout resolution"
        verbose_name_plural = "Seller payout resolutions"

        constraints = [
            models.UniqueConstraint(
                fields=["payout"],
                condition=models.Q(status="pending"),
                name="unique_pending_payout_resolution",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.investigation_id and self.payout_id:
            if self.investigation.payout_id != self.payout_id:
                errors["investigation"] = (
                    "Investigation must belong to the same payout."
                )

        if self.requested_by_id and self.approved_by_id:
            if self.requested_by_id == self.approved_by_id:
                errors["approved_by"] = (
                    "The requester cannot approve their own resolution."
                )

        if self.status == self.STATUS_PENDING:
            if self.approved_by_id or self.decided_at:
                errors["status"] = (
                    "Pending resolutions cannot have approval details."
                )
        else:
            if not self.approved_by_id:
                errors["approved_by"] = (
                    "An approving administrator is required."
                )

            if not self.decided_at:
                errors["decided_at"] = (
                    "A decision timestamp is required."
                )

        if not self.provider_reference.strip():
            errors["provider_reference"] = (
                "AzamPay evidence reference is required."
            )

        if not self.evidence.strip():
            errors["evidence"] = (
                "Supporting evidence is required."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Resolution #{self.pk} - "
            f"{self.payout.order_reference} - "
            f"{self.get_status_display()}"
        )


class SellerPayoutFinalization(models.Model):
    payout = models.OneToOneField(
        "SellerPayout",
        on_delete=models.PROTECT,
        related_name="manual_finalization",
    )

    resolution = models.OneToOneField(
        "SellerPayoutResolution",
        on_delete=models.PROTECT,
        related_name="finalization",
    )

    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="manual_payout_finalizations",
    )

    outcome = models.CharField(
        max_length=30,
        choices=SellerPayoutResolution.OUTCOME_CHOICES,
    )

    provider_reference = models.CharField(max_length=150)
    verification_method = models.CharField(max_length=100)
    verification_evidence = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Manual finalization for payout {self.payout_id}"
