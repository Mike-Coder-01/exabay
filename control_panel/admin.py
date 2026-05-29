from django.contrib import admin

from .models import AdminNotification, SellerPayout, SellerVerificationReview


@admin.register(SellerVerificationReview)
class SellerVerificationReviewAdmin(admin.ModelAdmin):
    list_display = ("seller", "status", "reviewed_by", "reviewed_at", "updated_at")
    list_filter = ("status", "reviewed_at")
    search_fields = ("seller__business_name", "seller__user__username", "seller__user__email", "reason")


@admin.register(AdminNotification)
class AdminNotificationAdmin(admin.ModelAdmin):
    list_display = ("subject", "recipient", "notification_type", "sender", "created_at", "is_read")
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("subject", "message", "recipient__username", "recipient__email")


@admin.register(SellerPayout)
class SellerPayoutAdmin(admin.ModelAdmin):
    list_display = (
        "order_reference",
        "seller",
        "amount",
        "currency",
        "status",
        "phone_number",
        "channel_provider",
        "created_at",
    )
    list_filter = ("status", "currency", "channel_provider", "created_at")
    search_fields = (
        "order_reference",
        "seller__business_name",
        "seller__user__username",
        "seller__user__email",
        "phone_number",
    )
    readonly_fields = ("preview_response", "gateway_response", "created_at", "updated_at")
    filter_horizontal = ("order_items",)
