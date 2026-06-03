from django.contrib import admin

from .models import DigestPreference, Notification, NotificationRule


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    list_display = ("rule_type", "farm", "enabled", "updated_at")
    list_filter = ("rule_type", "enabled")
    search_fields = ("farm__name",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("type", "user", "title", "is_read", "created_at")
    list_filter = ("type", "is_read")
    search_fields = ("title", "dedupe_key", "user__phone")
    readonly_fields = ("created_at",)


@admin.register(DigestPreference)
class DigestPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "enabled", "send_hour", "last_sent_on")
    list_filter = ("enabled",)
