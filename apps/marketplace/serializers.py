from __future__ import annotations

from rest_framework import serializers

from .badge import is_verified_seller
from .models import Listing


class ListingSerializer(serializers.ModelSerializer):
    farm_name = serializers.SerializerMethodField()
    region = serializers.CharField(required=False, allow_blank=True)
    verified_seller = serializers.SerializerMethodField()
    price_naira = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "id", "farm", "farm_name", "title", "kind", "description",
            "quantity", "unit", "price_kobo", "price_naira", "price_is_per_unit",
            "region", "contact_phone", "photo_keys", "status",
            "verified_seller", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "farm", "farm_name", "verified_seller", "price_naira",
            "created_at", "updated_at",
        )

    def get_farm_name(self, obj):
        return obj.farm.name

    def get_verified_seller(self, obj):
        return is_verified_seller(obj.farm)

    def get_price_naira(self, obj):
        return round(obj.price_kobo / 100, 2)
