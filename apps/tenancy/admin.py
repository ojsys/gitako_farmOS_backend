from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    list_display = ("at", "target_table", "target_id_short", "action", "actor_user", "tenant_id")
    list_filter = ("target_table", "action", "at")
    search_fields = ("target_id", "actor_user__phone")
    readonly_fields = [f.name for f in AuditEntry._meta.fields]
    date_hierarchy = "at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description="Target")
    def target_id_short(self, obj):
        return str(obj.target_id)[:8] + "…"
