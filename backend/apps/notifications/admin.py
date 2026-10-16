from django.contrib import admin

from apps.notifications.models import EmailPreference, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["recipient", "event", "created_at", "read_at"]
    list_filter = ["event"]
    search_fields = ["recipient__nickname"]
    readonly_fields = ["recipient", "event", "actor", "target_content_type", "target_object_id", "payload", "created_at", "read_at"]

    def has_add_permission(self, request) -> bool:
        return False


@admin.register(EmailPreference)
class EmailPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "email_enabled", "updated_at"]
    list_filter = ["email_enabled"]
    search_fields = ["user__nickname"]
