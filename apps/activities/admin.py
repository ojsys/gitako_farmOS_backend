from django.contrib import admin
from django.utils.html import format_html

from .models import Activity


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = (
        "type_label", "enterprise_name", "performed_short", "recorded_short",
        "occurred_at", "weather_chip", "cost_naira", "has_photo", "approval_chip",
    )
    list_filter = ("type", "weather", "approved_at", "occurred_at")
    search_fields = (
        "type", "notes", "enterprise__name",
        "actor_user__phone", "actor_user__email",
        "performed_by__phone", "performed_by__email",
    )
    raw_id_fields = ("enterprise", "actor_user", "performed_by", "approved_by")
    readonly_fields = (
        "id", "tenant_id", "created_at", "updated_at", "deleted_at", "client_seq",
        "approved_at", "approved_by",
    )
    date_hierarchy = "occurred_at"
    fieldsets = (
        ("What", {"fields": ("id", "type", "enterprise", "occurred_at", "weather")}),
        ("Who", {"fields": ("performed_by", "actor_user")}),
        ("Details", {"fields": ("notes", "attrs", "cost_kobo", "photo_keys", "gps_lat", "gps_lng")}),
        ("Approval", {"fields": ("approved_at", "approved_by")}),
        ("Audit", {"fields": ("tenant_id", "created_at", "updated_at", "deleted_at", "client_seq")}),
    )
    actions = ["approve_selected"]

    @admin.display(description="Activity", ordering="type")
    def type_label(self, obj):
        return obj.type.replace("_", " ").title()

    @admin.display(description="Enterprise", ordering="enterprise__name")
    def enterprise_name(self, obj):
        return obj.enterprise.name if obj.enterprise_id else "—"

    @admin.display(description="Performed by")
    def performed_short(self, obj):
        u = obj.performed_by or obj.actor_user
        if not u:
            return "—"
        return u.full_name or u.phone or u.email or "—"

    @admin.display(description="Recorded by")
    def recorded_short(self, obj):
        if not obj.actor_user_id:
            return "—"
        u = obj.actor_user
        return u.full_name or u.phone or u.email or "—"

    @admin.display(description="Cost", ordering="cost_kobo")
    def cost_naira(self, obj):
        return f"₦{obj.cost_kobo / 100:,.0f}" if obj.cost_kobo else "—"

    @admin.display(boolean=True, description="Photo")
    def has_photo(self, obj):
        return bool(obj.photo_keys)

    @admin.display(description="Status")
    def approval_chip(self, obj):
        approved = obj.approved_at is not None
        color = "#1F8B4C" if approved else "#B8761F"
        label = "Approved" if approved else "Pending"
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600;font-size:11px;letter-spacing:0.4px;text-transform:uppercase;">{}</span>',
            color, color, label,
        )

    @admin.display(description="Weather", ordering="weather")
    def weather_chip(self, obj):
        if not obj.weather:
            return "—"
        palette = {
            "just_rained": ("#1F6F8B", "🌧"),
            "about_to_rain": ("#B8761F", "☁️"),
            "clear": ("#1F8B4C", "☀️"),
        }
        color, icon = palette.get(obj.weather, ("#5A6760", ""))
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600;font-size:11px;">{} {}</span>',
            color, color, icon, obj.get_weather_display(),
        )

    @admin.action(description="Approve selected activities")
    def approve_selected(self, request, queryset):
        from django.utils import timezone
        count = queryset.filter(approved_at__isnull=True).update(
            approved_at=timezone.now(), approved_by=request.user,
        )
        self.message_user(request, f"Approved {count} activity(ies).")
