"""Inventory primitives — Store · InventoryItem · InventoryMovement.

The PRD M4 mental model:
- A **Store** is a physical location where stock lives (main store, seed shed,
  feed bunker, cold box). A farm has one or more.
- An **InventoryItem** is a tradeable thing (NPK 20-10-10, grower feed, Newcastle
  vaccine). Items are farm-scoped. Each item has a category, unit, valuation
  method (weighted-avg default), and optional reorder_level.
- An **InventoryMovement** is the ledger entry that changes stock. Four ops:
  - `receipt`    — stock came in (purchase, transfer-in)
  - `issue`      — stock went out to an enterprise (planting consumed seed)
  - `transfer`   — moved between stores within the same farm (paired rows)
  - `adjustment` — loss / theft / breakage / count correction
Quantity is signed for raw math: issues are negative, receipts positive.
Stock-on-hand = SUM(qty) filtered to a store/item.
"""
from __future__ import annotations

from django.db import models

from apps.activities.models import Activity
from apps.farms.models import Farm
from apps.tenancy.models import TenantScopedModel


class Store(TenantScopedModel):
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=120)
    location_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["farm", "name"], name="uniq_store_per_farm"),
        ]

    def __str__(self) -> str:
        return self.name


class InventoryItem(TenantScopedModel):
    CATEGORY_CHOICES = [
        ("seed", "Seed"),
        ("fertilizer", "Fertilizer"),
        ("pesticide", "Pesticide / agrochemical"),
        ("feed", "Feed"),
        ("vet", "Vet supplies / drugs"),
        ("produce", "Harvested produce"),
        ("livestock", "Live animals / birds"),
        ("processed", "Processed goods"),
        ("supplies", "Tools & supplies"),
        ("other", "Other"),
    ]

    VALUATION_WEIGHTED_AVG = "weighted_avg"
    VALUATION_FIFO = "fifo"
    VALUATION_CHOICES = [
        (VALUATION_WEIGHTED_AVG, "Weighted average"),
        (VALUATION_FIFO, "FIFO"),
    ]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="inventory_items")
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES, default="other")
    unit = models.CharField(max_length=24, default="unit",
                            help_text="bags, kg, L, doses, birds, units…")
    valuation_method = models.CharField(
        max_length=16, choices=VALUATION_CHOICES, default=VALUATION_WEIGHTED_AVG,
    )
    reorder_level = models.DecimalField(
        max_digits=14, decimal_places=3, default=0,
        help_text="Trigger 'low stock' when on-hand drops below this.",
    )
    sku = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(fields=["farm", "name"], name="uniq_item_per_farm"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.unit})"


class InventoryMovement(TenantScopedModel):
    OP_RECEIPT = "receipt"
    OP_ISSUE = "issue"
    OP_TRANSFER = "transfer"
    OP_ADJUSTMENT = "adjustment"
    OP_CHOICES = [
        (OP_RECEIPT, "Receipt"),
        (OP_ISSUE, "Issue"),
        (OP_TRANSFER, "Transfer"),
        (OP_ADJUSTMENT, "Adjustment"),
    ]

    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name="movements")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="movements")
    op = models.CharField(max_length=12, choices=OP_CHOICES)
    qty = models.DecimalField(
        max_digits=14, decimal_places=3,
        help_text="Signed for raw math: issues are negative, receipts positive.",
    )
    unit_cost_kobo = models.BigIntegerField(
        default=0,
        help_text="Per-unit cost in kobo at the time of this movement.",
    )
    ref_activity = models.ForeignKey(
        Activity, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="inventory_movements",
        help_text="Set when this movement was caused by an activity.",
    )
    transfer_pair_id = models.UUIDField(
        null=True, blank=True,
        help_text="Two paired movements share this id for a transfer.",
    )
    notes = models.TextField(blank=True)
    occurred_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["item", "store", "-occurred_at"]),
            models.Index(fields=["tenant_id", "-occurred_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.op} {self.qty} {self.item.unit} of {self.item.name}"
