from django.contrib import admin
from django.utils.html import format_html

from .models import ChangeLog, SyncCursor, SyncNote, SyncTag


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    list_display = ("server_seq", "tenant_id", "table", "op_chip", "row_short",
                    "actor_short", "device_id", "at")
    list_filter = ("table", "op", "at")
    search_fields = ("row_id", "device_id", "actor_user__phone")
    readonly_fields = [f.name for f in ChangeLog._meta.fields]
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Op", ordering="op")
    def op_chip(self, obj):
        palette = {"insert": "#1F8B4C", "update": "#1F6F8B", "delete": "#B23A2B"}
        color = palette.get(obj.op, "#5A6760")
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:6px;'
            'font-weight:600;font-size:11px;text-transform:uppercase;">{}</span>',
            color, color, obj.op,
        )

    @admin.display(description="Row")
    def row_short(self, obj):
        return str(obj.row_id)[:8] + "…"

    @admin.display(description="By")
    def actor_short(self, obj):
        return obj.actor_user.phone if obj.actor_user_id else "—"


@admin.register(SyncCursor)
class SyncCursorAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant_id", "device_id", "last_server_seq_acked", "last_pull_at")
    list_filter = ("last_pull_at",)
    search_fields = ("user__phone", "device_id")
    readonly_fields = ("id", "updated_at")


@admin.register(SyncNote)
class SyncNoteAdmin(admin.ModelAdmin):
    list_display = ("title", "tenant_id", "updated_at")
    search_fields = ("title", "body")
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at", "deleted_at", "client_seq")


@admin.register(SyncTag)
class SyncTagAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "tenant_id", "updated_at")
    search_fields = ("name",)
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at", "deleted_at", "client_seq")
