from __future__ import annotations

from rest_framework import serializers

from .models import DeveloperModule, ModuleInstall


class DeveloperModuleSerializer(serializers.ModelSerializer):
    developer_name = serializers.SerializerMethodField()

    class Meta:
        model = DeveloperModule
        fields = (
            "id", "developer", "developer_name", "name", "slug", "category",
            "description", "price_kobo", "revenue_share_pct", "status",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_developer_name(self, obj):
        return obj.developer.name


class ModuleInstallSerializer(serializers.ModelSerializer):
    module_name = serializers.SerializerMethodField()

    class Meta:
        model = ModuleInstall
        fields = (
            "id", "module", "module_name", "farm", "is_active", "price_kobo",
            "gitako_cut_kobo", "developer_take_kobo", "payment_reference",
            "installed_at", "uninstalled_at",
        )
        read_only_fields = fields

    def get_module_name(self, obj):
        return obj.module.name
