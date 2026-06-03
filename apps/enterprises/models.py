"""Enterprise — a discrete production unit inside a farm.

Polymorphic by `type` + `attrs` JSONB. The PRD lists five types (crop_cycle,
flock, herd, pond, processing_line); Phase 1 shipped **crop_cycle** and
**flock**, Phase 2 M9 adds **herd** (livestock: cattle, small ruminants, pigs).
New types extend without breaking the schema (PRD §4).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.farms.models import Farm
from apps.tenancy.models import TenantScopedModel


class Enterprise(TenantScopedModel):
    TYPE_CROP = "crop_cycle"
    TYPE_FLOCK = "flock"
    TYPE_HERD = "herd"
    TYPE_POND = "pond"
    TYPE_PROCESSING = "processing_line"
    TYPE_CHOICES = [
        (TYPE_CROP, "Crop cycle"),
        (TYPE_FLOCK, "Poultry flock"),
        (TYPE_HERD, "Livestock herd"),
        (TYPE_POND, "Fish pond"),
        (TYPE_PROCESSING, "Processing line"),
    ]

    LIFECYCLE_PLANNED = "planned"
    LIFECYCLE_ACTIVE = "active"
    LIFECYCLE_COMPLETED = "completed"
    LIFECYCLE_ABANDONED = "abandoned"
    LIFECYCLE_CHOICES = [
        (LIFECYCLE_PLANNED, "Planned"),
        (LIFECYCLE_ACTIVE, "Active"),
        (LIFECYCLE_COMPLETED, "Completed"),
        (LIFECYCLE_ABANDONED, "Abandoned"),
    ]

    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="enterprises")
    type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    name = models.CharField(max_length=120)
    lifecycle_state = models.CharField(
        max_length=16, choices=LIFECYCLE_CHOICES, default=LIFECYCLE_PLANNED,
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    attrs = models.JSONField(default=dict)
    # attrs:
    #   crop_cycle: {crop, variety?, area_ha, planting_date, expected_harvest_date}
    #   flock:      {kind: broiler|layer|breeder, batch_id?, stocking_date, bird_count}
    #   herd:       {species: cattle|goat|sheep|pig, breed?, herd_size, acquisition_date}
    #   pond:       {species: catfish|tilapia|other, pond_type?, stocking_date, fingerling_count}
    #   processing_line: {process: e.g. cassava_garri|maize_meal|milk_yogurt, input_item?, output_item?, started_on}

    class Meta:
        ordering = ["-start_date", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_type_display()})"


class EnterprisePlan(TenantScopedModel):
    """The "Plan a season" budget + expected outcome for an enterprise.

    One per enterprise. Budget lines + expected revenue inputs are user-entered;
    totals + break-even + ROI are computed in the serializer so they stay
    consistent.

    `budget_lines` shape:
      [{"id": "fert", "label": "Fertilizer", "icon": "seed", "planned_kobo": 42000000}, ...]
    """

    enterprise = models.OneToOneField(
        Enterprise, on_delete=models.CASCADE, related_name="plan",
    )
    budget_lines = models.JSONField(default=list)
    expected_yield_kg = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Total expected yield in kg (crops) or total kg of birds (flocks).",
    )
    expected_unit_price_kobo = models.BigIntegerField(
        null=True, blank=True,
        help_text="Expected price per kg in kobo.",
    )
    price_reference = models.CharField(
        max_length=120, blank=True,
        help_text="Free text — e.g. 'Iseyin market avg.' or 'Sayedero contract'.",
    )
    notes = models.TextField(blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Plan for {self.enterprise_id}"


class SeasonTask(TenantScopedModel):
    """A materialized GAP-calendar task for an enterprise.

    Generated from the crop/flock/herd/pond template anchored on the planting
    (or stocking/acquisition) date. Unlike the on-the-fly `planned_tasks`
    calendar, these are persistent rows a manager can assign to a farm hand and
    a farm hand can carry out and complete — closing the plan→do→track loop.

    A task auto-completes when a matching Activity is logged (see
    apps/enterprises/signals.py), linking the two.
    """

    STATUS_PENDING = "pending"
    STATUS_DONE = "done"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DONE, "Done"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    enterprise = models.ForeignKey(
        Enterprise, on_delete=models.CASCADE, related_name="season_tasks",
    )
    activity_type = models.CharField(max_length=32)
    label = models.CharField(max_length=160)
    notes = models.TextField(blank=True)
    target_date = models.DateField(db_index=True)
    source = models.CharField(max_length=32, blank=True)
    # Stable key per logical task slot so generation is idempotent
    # (re-running never duplicates): "{activity_type}:{target_date}".
    slot_key = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_tasks",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_activity = models.ForeignKey(
        "activities.Activity", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["target_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["enterprise", "slot_key"], name="uniq_seasontask_slot",
            ),
        ]
        indexes = [
            models.Index(fields=["enterprise", "status", "target_date"]),
            models.Index(fields=["assigned_to", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.label} @ {self.target_date} ({self.status})"
