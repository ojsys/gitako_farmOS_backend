from __future__ import annotations

from rest_framework import serializers
from rest_framework.fields import empty

from .models import Farm, Party, StaffMembership


class _LatLngField(serializers.Field):
    """Wire format {"lat", "lng"} ↔ two float columns on the model.

    Uses source='*' so it reads/writes a pair of fields on the instance — keeps
    the API identical to the old PostGIS Point while storing plain floats.
    """

    def __init__(self, lat_field, lng_field, **kwargs):
        self.lat_field, self.lng_field = lat_field, lng_field
        kwargs["source"] = "*"
        super().__init__(**kwargs)

    def run_validation(self, data=empty):
        if data is empty:
            raise serializers.SkipField()
        return self.to_internal_value(data)

    def to_representation(self, obj):
        lat = getattr(obj, self.lat_field)
        lng = getattr(obj, self.lng_field)
        return None if lat is None or lng is None else {"lat": lat, "lng": lng}

    def to_internal_value(self, data):
        if data is None:
            return {self.lat_field: None, self.lng_field: None}
        try:
            return {self.lat_field: float(data["lat"]), self.lng_field: float(data["lng"])}
        except (KeyError, ValueError, TypeError) as exc:
            raise serializers.ValidationError(f"Invalid point: {exc}") from exc


class _GeoJSONField(serializers.Field):
    """Wire format: a GeoJSON geometry dict ↔ a JSON column on the model."""

    def __init__(self, model_field, **kwargs):
        # NB: not `self.field_name` — DRF reserves that and rebinds it to the
        # declared serializer field name during binding.
        self.model_field = model_field
        kwargs["source"] = "*"
        super().__init__(**kwargs)

    def run_validation(self, data=empty):
        if data is empty:
            raise serializers.SkipField()
        return self.to_internal_value(data)

    def to_representation(self, obj):
        return getattr(obj, self.model_field) or None

    def to_internal_value(self, data):
        if data is None:
            return {self.model_field: None}
        if not isinstance(data, dict) or "coordinates" not in data:
            raise serializers.ValidationError(
                "Expected a GeoJSON geometry with a 'coordinates' key."
            )
        return {self.model_field: data}


class FarmSerializer(serializers.ModelSerializer):
    location = _LatLngField("location_lat", "location_lng", required=False)
    boundary = _GeoJSONField("boundary_geojson", required=False)
    role = serializers.SerializerMethodField()

    class Meta:
        model = Farm
        fields = (
            "id", "name", "owner", "location", "boundary", "address_text",
            "region", "modules_enabled", "created_at", "updated_at", "role",
        )
        read_only_fields = ("id", "owner", "created_at", "updated_at")

    def get_role(self, obj: Farm) -> str | None:
        user = self.context.get("request").user if self.context.get("request") else None
        if not user or not user.is_authenticated:
            return None
        membership = obj.memberships.filter(user=user).only("role").first()
        return membership.role if membership else None

    def create(self, validated_data: dict) -> Farm:
        request = self.context["request"]
        farm = Farm.objects.create(owner=request.user, **validated_data)
        StaffMembership.objects.create(
            user=request.user, farm=farm, role=StaffMembership.ROLE_OWNER,
            accepted_at=farm.created_at,
        )
        return farm


class StaffMembershipSerializer(serializers.ModelSerializer):
    user_phone = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = StaffMembership
        fields = (
            "id", "user", "user_phone", "user_name", "farm",
            "role", "invited_at", "accepted_at",
        )
        read_only_fields = ("id", "invited_at")

    def get_user_phone(self, obj):
        return obj.user.phone

    def get_user_name(self, obj):
        return obj.user.full_name or ""


class StaffInviteSerializer(serializers.Serializer):
    """POST /api/farms/{id}/invite — bring in a teammate by phone.

    Creates the user if needed (no auth yet for them — they'll log in via OTP
    on their own device). Idempotent on (user, farm).
    """

    phone = serializers.CharField()
    role = serializers.ChoiceField(choices=StaffMembership.ROLE_CHOICES)
    full_name = serializers.CharField(required=False, allow_blank=True)


class PartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ("id", "name", "kind", "contact_json", "nin_bvn", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")
