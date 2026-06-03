from __future__ import annotations

from rest_framework import serializers

from .models import InventoryItem, InventoryMovement, Store


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = (
            "id", "farm", "tenant_id", "name", "location_note",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "farm", "tenant_id", "created_at", "updated_at")


class InventoryItemSerializer(serializers.ModelSerializer):
    on_hand = serializers.SerializerMethodField()
    value_kobo = serializers.SerializerMethodField()
    is_low_stock = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = (
            "id", "farm", "tenant_id", "name", "category", "unit",
            "valuation_method", "reorder_level", "sku",
            "on_hand", "value_kobo", "is_low_stock",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "farm", "tenant_id",
            "on_hand", "value_kobo", "is_low_stock",
            "created_at", "updated_at",
        )

    def get_on_hand(self, obj):
        return _stock_qty(obj)

    def get_value_kobo(self, obj):
        return _stock_value_kobo(obj)

    def get_is_low_stock(self, obj):
        return float(_stock_qty(obj)) < float(obj.reorder_level)


class InventoryMovementSerializer(serializers.ModelSerializer):
    item_name = serializers.SerializerMethodField()
    item_unit = serializers.SerializerMethodField()
    store_name = serializers.SerializerMethodField()

    class Meta:
        model = InventoryMovement
        fields = (
            "id", "tenant_id", "item", "store", "op", "qty",
            "unit_cost_kobo", "ref_activity", "transfer_pair_id",
            "notes", "occurred_at",
            "item_name", "item_unit", "store_name",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "item_name", "item_unit", "store_name",
            "created_at", "updated_at",
        )

    def get_item_name(self, obj):
        return obj.item.name

    def get_item_unit(self, obj):
        return obj.item.unit

    def get_store_name(self, obj):
        return obj.store.name


# ---------- helpers ----------

def _stock_qty(item: InventoryItem) -> float:
    """Sum of all movement qty for the item (signed). Stock-on-hand."""
    from django.db.models import Sum
    return float(
        item.movements.filter(deleted_at__isnull=True)
        .aggregate(s=Sum("qty"))["s"] or 0
    )


def _stock_value_kobo(item: InventoryItem) -> int:
    """Weighted-average value of current stock-on-hand.

    avg_cost = sum(receipt_qty * unit_cost) / sum(receipt_qty)
    value = max(on_hand, 0) * avg_cost
    """
    from django.db.models import F, Sum

    qty = _stock_qty(item)
    if qty <= 0:
        return 0
    agg = (
        item.movements.filter(
            deleted_at__isnull=True,
            op__in=[InventoryMovement.OP_RECEIPT, InventoryMovement.OP_ADJUSTMENT],
            qty__gt=0,
        )
        .aggregate(
            total_qty=Sum("qty"),
            total_value=Sum(F("qty") * F("unit_cost_kobo")),
        )
    )
    total_qty = float(agg["total_qty"] or 0)
    total_value = float(agg["total_value"] or 0)
    if total_qty <= 0:
        return 0
    avg_cost = total_value / total_qty
    return int(qty * avg_cost)
