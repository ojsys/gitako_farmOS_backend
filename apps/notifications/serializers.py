from __future__ import annotations

from rest_framework import serializers

from .models import DigestPreference, Notification, NotificationRule


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = (
            "id", "type", "title", "body", "data", "tenant_id",
            "is_read", "read_at", "channels_sent", "created_at",
        )
        read_only_fields = fields


class DigestPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DigestPreference
        fields = ("enabled", "send_hour", "last_sent_on", "updated_at")
        read_only_fields = ("last_sent_on", "updated_at")

    def validate_send_hour(self, value):
        if not 0 <= value <= 23:
            raise serializers.ValidationError("send_hour must be between 0 and 23.")
        return value


class NotificationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationRule
        fields = ("id", "farm", "rule_type", "enabled", "params", "channels", "updated_at")
        read_only_fields = ("id", "farm", "updated_at")
