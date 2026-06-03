from django.contrib import admin
from django.utils.html import format_html

from .models import Farm, Party, StaffMembership


class StaffInline(admin.TabularInline):
    model = StaffMembership
    extra = 0
    raw_id_fields = ("user",)
    fields = ("user", "role", "invited_at", "accepted_at")
    readonly_fields = ("invited_at",)


@admin.register(Farm)
class FarmAdmin(admin.ModelAdmin):
    list_display = ("name", "owner_phone", "region", "members_count", "created_at", "alive")
    list_filter = ("region", "created_at")
    search_fields = ("name", "owner__phone", "owner__full_name", "region", "address_text")
    raw_id_fields = ("owner",)
    readonly_fields = ("id", "created_at", "updated_at", "deleted_at")
    inlines = [StaffInline]
    fieldsets = (
        ("Identity", {"fields": ("id", "name", "owner")}),
        ("Location", {"fields": ("region", "address_text", "location_lat", "location_lng", "boundary_geojson")}),
        ("Config", {"fields": ("modules_enabled",)}),
        ("Audit", {"fields": ("created_at", "updated_at", "deleted_at", "client_seq")}),
    )

    @admin.display(description="Owner")
    def owner_phone(self, obj):
        return obj.owner.phone if obj.owner else "—"

    @admin.display(description="Staff")
    def members_count(self, obj):
        return obj.memberships.count()

    @admin.display(boolean=True, description="Live")
    def alive(self, obj):
        return obj.deleted_at is None


@admin.register(StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    list_display = ("user_phone", "farm_name", "role_badge", "accepted", "invited_at")
    list_filter = ("role",)
    search_fields = ("user__phone", "user__full_name", "farm__name")
    raw_id_fields = ("user", "farm")
    readonly_fields = ("id", "invited_at")

    @admin.display(description="User")
    def user_phone(self, obj):
        return f"{obj.user.full_name or '—'} · {obj.user.phone}"

    @admin.display(description="Farm")
    def farm_name(self, obj):
        return obj.farm.name

    @admin.display(boolean=True, description="Accepted")
    def accepted(self, obj):
        return obj.accepted_at is not None

    @admin.display(description="Role")
    def role_badge(self, obj):
        palette = {
            "owner": "#1F5A38",
            "manager": "#1F8B4C",
            "field_staff": "#5A6760",
            "viewer": "#B6B6B6",
        }
        color = palette.get(obj.role, "#5A6760")
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600;font-size:11px;letter-spacing:0.4px;text-transform:uppercase;">{}</span>',
            color, color, obj.get_role_display(),
        )


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "tenant_id", "created_at")
    list_filter = ("kind",)
    search_fields = ("name",)
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at", "deleted_at")
