from __future__ import annotations

from rest_framework import serializers

from .models import Contract, Offer


class OfferSerializer(serializers.ModelSerializer):
    listing_title = serializers.SerializerMethodField()
    buyer_phone = serializers.SerializerMethodField()

    class Meta:
        model = Offer
        fields = (
            "id", "listing", "listing_title", "buyer", "buyer_phone",
            "quantity", "offer_price_kobo", "message", "status",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "buyer", "buyer_phone", "listing_title", "status",
                            "created_at", "updated_at")

    def get_listing_title(self, obj):
        return obj.listing.title

    def get_buyer_phone(self, obj):
        return obj.buyer.phone


class ContractSerializer(serializers.ModelSerializer):
    listing_title = serializers.SerializerMethodField()
    seller_farm_name = serializers.SerializerMethodField()
    buyer_phone = serializers.SerializerMethodField()

    class Meta:
        model = Contract
        fields = (
            "id", "offer", "listing", "listing_title", "seller_farm", "seller_farm_name",
            "buyer", "buyer_phone", "amount_kobo", "state", "qa_result", "qa_notes",
            "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_listing_title(self, obj):
        return obj.listing.title

    def get_seller_farm_name(self, obj):
        return obj.seller_farm.name

    def get_buyer_phone(self, obj):
        return obj.buyer.phone
