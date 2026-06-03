from django.contrib import admin

from .models import ApiKey, ConsentGrant, Partner, PartnerAuditEntry


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "is_active", "rate_limit_per_min", "created_at")
    list_filter = ("kind", "is_active")
    search_fields = ("name", "contact_email")


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("partner", "prefix", "label", "is_active", "last_used_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("partner__name", "prefix", "label")
    readonly_fields = ("key_hash", "prefix", "last_used_at")


@admin.register(ConsentGrant)
class ConsentGrantAdmin(admin.ModelAdmin):
    list_display = ("farm", "partner", "is_active", "granted_at", "revoked_at")
    list_filter = ("is_active",)
    search_fields = ("farm__name", "partner__name")
    raw_id_fields = ("farm", "partner")


@admin.register(PartnerAuditEntry)
class PartnerAuditEntryAdmin(admin.ModelAdmin):
    list_display = ("partner", "path", "scope", "status_code", "farm", "at")
    list_filter = ("scope", "status_code")
    search_fields = ("partner__name", "path")
    readonly_fields = ("partner", "path", "farm", "scope", "status_code", "at")
