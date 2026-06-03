from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import OtpCode, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("phone", "full_name", "email", "is_active", "is_staff", "date_joined")
    search_fields = ("phone", "email", "full_name")
    ordering = ("-date_joined",)
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Profile", {"fields": ("full_name", "email", "preferred_language")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("phone", "password1", "password2")}),
    )
    readonly_fields = ("date_joined",)


@admin.register(OtpCode)
class OtpCodeAdmin(admin.ModelAdmin):
    list_display = ("phone", "purpose", "created_at", "expires_at", "consumed_at", "attempts")
    search_fields = ("phone",)
    list_filter = ("purpose",)
    readonly_fields = ("code", "created_at", "expires_at")
