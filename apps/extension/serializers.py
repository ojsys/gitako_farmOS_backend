from __future__ import annotations

from rest_framework import serializers

from .models import Advisory, OfficerAccess, Visit


class OfficerAccessSerializer(serializers.ModelSerializer):
    officer_phone = serializers.SerializerMethodField()
    officer_name = serializers.SerializerMethodField()
    farm_name = serializers.SerializerMethodField()

    class Meta:
        model = OfficerAccess
        fields = (
            "id", "officer", "officer_phone", "officer_name", "farm", "farm_name",
            "program", "status", "requested_at", "approved_at",
        )
        read_only_fields = fields

    def get_officer_phone(self, obj):
        return obj.officer.phone

    def get_officer_name(self, obj):
        return obj.officer.full_name or ""

    def get_farm_name(self, obj):
        return obj.farm.name


class AdvisorySerializer(serializers.ModelSerializer):
    officer_name = serializers.SerializerMethodField()
    farm_name = serializers.SerializerMethodField()

    class Meta:
        model = Advisory
        fields = (
            "id", "officer", "officer_name", "farm", "farm_name",
            "title", "body", "severity", "created_at",
        )
        read_only_fields = ("id", "officer", "officer_name", "farm_name", "created_at")

    def get_officer_name(self, obj):
        return (obj.officer.full_name or obj.officer.phone) if obj.officer_id else ""

    def get_farm_name(self, obj):
        return obj.farm.name


class VisitSerializer(serializers.ModelSerializer):
    farm_name = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = (
            "id", "officer", "farm", "farm_name", "scheduled_for", "purpose",
            "status", "intervention_notes", "created_at", "updated_at",
        )
        read_only_fields = ("id", "officer", "farm_name", "created_at", "updated_at")

    def get_farm_name(self, obj):
        return obj.farm.name
