from django.contrib import admin
from django.utils.html import format_html

from .models import InventoryItem, InventoryMovement, Store
from .serializers import _stock_qty, _stock_value_kobo


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "farm", "items_count", "created_at")
    search_fields = ("name", "farm__name")
    raw_id_fields = ("farm",)
    readonly_fields = ("id", "tenant_id", "created_at", "updated_at", "deleted_at")

    @admin.display(description="Movements")
    def items_count(self, obj):
        return obj.movements.count()


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = (
        "name", "category", "unit", "on_hand_display", "value_display",
        "low_stock_chip", "farm",
    )
    list_filter = ("category", "valuation_method")
    search_fields = ("name", "sku", "farm__name")
    raw_id_fields = ("farm",)
    readonly_fields = (
        "id", "tenant_id", "created_at", "updated_at", "deleted_at",
        "on_hand_display", "value_display",
    )
    fieldsets = (
        ("Identity", {"fields": ("id", "name", "sku", "category", "unit")}),
        ("Farm", {"fields": ("farm", "tenant_id")}),
        ("Valuation", {"fields": ("valuation_method", "reorder_level")}),
        ("Live", {"fields": ("on_hand_display", "value_display")}),
        ("Audit", {"fields": ("created_at", "updated_at", "deleted_at")}),
    )

    @admin.display(description="On hand")
    def on_hand_display(self, obj):
        return f"{_stock_qty(obj):.1f} {obj.unit}"

    @admin.display(description="Value")
    def value_display(self, obj):
        return f"₦{_stock_value_kobo(obj) / 100:,.0f}"

    @admin.display(description="Stock")
    def low_stock_chip(self, obj):
        qty = _stock_qty(obj)
        low = float(qty) < float(obj.reorder_level)
        color = "#B8761F" if low else "#1F8B4C"
        label = "Low" if low else "OK"
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:999px;'
            'font-weight:600;font-size:11px;letter-spacing:0.4px;text-transform:uppercase;">{}</span>',
            color, color, label,
        )


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ("occurred_at", "op_chip", "qty_display", "item",
                    "store", "ref_activity")
    list_filter = ("op", "store", "occurred_at")
    search_fields = ("item__name", "store__name", "notes")
    raw_id_fields = ("item", "store", "ref_activity")
    readonly_fields = (
        "id", "tenant_id", "transfer_pair_id",
        "created_at", "updated_at", "deleted_at",
    )
    date_hierarchy = "occurred_at"

    @admin.display(description="Op", ordering="op")
    def op_chip(self, obj):
        palette = {
            "receipt": ("#1F8B4C", "+"),
            "issue": ("#B23A2B", "−"),
            "transfer": ("#1F6F8B", "↔"),
            "adjustment": ("#B8761F", "Δ"),
        }
        color, icon = palette.get(obj.op, ("#5A6760", ""))
        return format_html(
            '<span style="background:{}1A;color:{};padding:2px 8px;border-radius:6px;'
            'font-weight:600;font-size:11px;text-transform:uppercase;">{} {}</span>',
            color, color, icon, obj.op,
        )

    @admin.display(description="Qty", ordering="qty")
    def qty_display(self, obj):
        return f"{obj.qty} {obj.item.unit}"
