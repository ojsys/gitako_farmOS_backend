from django.contrib import admin

from .models import Advisory, OfficerAccess, Visit


@admin.register(OfficerAccess)
class OfficerAccessAdmin(admin.ModelAdmin):
    list_display = ("officer", "farm", "program", "status", "requested_at", "approved_at")
    list_filter = ("status",)
    search_fields = ("officer__phone", "farm__name", "program")
    raw_id_fields = ("officer", "farm")


@admin.register(Advisory)
class AdvisoryAdmin(admin.ModelAdmin):
    list_display = ("title", "farm", "officer", "severity", "created_at")
    list_filter = ("severity",)
    search_fields = ("title", "farm__name")
    raw_id_fields = ("officer", "farm")


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("farm", "officer", "scheduled_for", "status")
    list_filter = ("status",)
    raw_id_fields = ("officer", "farm")
