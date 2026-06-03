from __future__ import annotations

from rest_framework import serializers
from rest_framework.fields import empty

from .models import Activity


class _PointField(serializers.Field):
    """Wire format {"lat", "lng"} ↔ gps_lat / gps_lng float columns.

    source='*' so it reads/writes the pair of fields — the API is unchanged from
    the old PostGIS Point, but storage is plain floats (no GDAL/PostGIS).
    """

    def __init__(self, **kwargs):
        kwargs["source"] = "*"
        super().__init__(**kwargs)

    def run_validation(self, data=empty):
        if data is empty:
            raise serializers.SkipField()
        return self.to_internal_value(data)

    def to_representation(self, obj):
        lat = getattr(obj, "gps_lat")
        lng = getattr(obj, "gps_lng")
        return None if lat is None or lng is None else {"lat": lat, "lng": lng}

    def to_internal_value(self, data):
        if data is None:
            return {"gps_lat": None, "gps_lng": None}
        try:
            return {"gps_lat": float(data["lat"]), "gps_lng": float(data["lng"])}
        except (KeyError, ValueError, TypeError) as exc:
            raise serializers.ValidationError(f"Invalid point: {exc}") from exc


class ActivitySerializer(serializers.ModelSerializer):
    gps_point = _PointField(required=False)
    actor_user_phone = serializers.SerializerMethodField()
    performed_by_label = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = (
            "id", "enterprise", "tenant_id", "type",
            "actor_user", "actor_user_phone",
            "performed_by", "performed_by_label",
            "occurred_at", "weather", "gps_point", "photo_keys", "cost_kobo",
            "notes", "attrs",
            "approved_at", "approved_by", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "actor_user", "actor_user_phone",
            "performed_by_label",
            "approved_at", "approved_by", "created_at", "updated_at",
        )

    def get_actor_user_phone(self, obj):
        return obj.actor_user.phone if obj.actor_user_id else None

    def get_performed_by_label(self, obj):
        u = obj.performed_by
        if not u:
            return None
        return u.full_name or u.phone or u.email or ""
