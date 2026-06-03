from django.contrib import admin

from .models import DeveloperModule, ModuleInstall


@admin.register(DeveloperModule)
class DeveloperModuleAdmin(admin.ModelAdmin):
    list_display = ("name", "developer", "category", "price_kobo", "revenue_share_pct", "status")
    list_filter = ("status", "category")
    search_fields = ("name", "slug", "developer__name")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ModuleInstall)
class ModuleInstallAdmin(admin.ModelAdmin):
    list_display = ("module", "farm", "is_active", "price_kobo", "gitako_cut_kobo", "installed_at")
    list_filter = ("is_active",)
    raw_id_fields = ("module", "farm")
