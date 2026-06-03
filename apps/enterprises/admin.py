from django.contrib import admin
from django.utils.html import format_html

from .models import Enterprise, SeasonTask


@admin.register(Enterprise)
class EnterpriseAdmin(admin.ModelAdmin):
    list_display = (
        "name", "type_badge", "farm_link", "lifecycle_badge",
        "start_date", "activities_count", "created_at",
    )
    list_filter = ("type", "lifecycle_state", "start_date")
    search_fields = ("name", "farm__name", "attrs")
    raw_id_fields = ("farm",)
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at", "deleted_at", "client_seq")
    fieldsets = (
        ("Identity", {"fields": ("id", "name", "type", "lifecycle_state")}),
        ("Farm", {"fields": ("farm", "tenant_id")}),
        ("Lifecycle", {"fields": ("start_date", "end_date")}),
        ("Type-specific attrs", {"fields": ("attrs",)}),
        ("Audit", {"fields": ("created_at", "updated_at", "deleted_at", "client_seq")}),
    )

    @admin.display(description="Farm", ordering="farm__name")
    def farm_link(self, obj):
        return obj.farm.name

    @admin.display(description="Type", ordering="type")
    def type_badge(self, obj):
        palette = {
            "crop_cycle": "#1F5A38", "flock": "#624A2F", "herd": "#7A4A1F",
            "pond": "#1F6F8B", "processing_line": "#6B4FA0",
        }
        color = palette.get(obj.type, "#624A2F")
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:6px;'
            'font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.4px;">{}</span>',
            color, color, obj.get_type_display(),
        )

    @admin.display(description="State", ordering="lifecycle_state")
    def lifecycle_badge(self, obj):
        palette = {
            "planned": "#B8761F",
            "active": "#1F8B4C",
            "completed": "#5A6760",
            "abandoned": "#B23A2B",
        }
        color = palette.get(obj.lifecycle_state, "#5A6760")
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600;font-size:11px;letter-spacing:0.4px;text-transform:uppercase;">{}</span>',
            color, color, obj.lifecycle_state,
        )

    @admin.display(description="Activities")
    def activities_count(self, obj):
        return obj.activities.count()


@admin.register(SeasonTask)
class SeasonTaskAdmin(admin.ModelAdmin):
    list_display = ("label", "enterprise", "target_date", "status", "assigned_to", "source")
    list_filter = ("status", "source", "activity_type")
    search_fields = ("label", "enterprise__name")
    raw_id_fields = ("enterprise", "assigned_to", "completed_activity")
    readonly_fields = ("slot_key", "completed_at", "completed_activity")
