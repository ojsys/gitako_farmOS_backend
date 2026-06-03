"""Developer App Store — Beta (PRD M20).

"Third-party developers publish modules (vet booking, drone services, soil
testing, etc.). Revenue share with Gitako."

A DeveloperModule is published by a Partner (reusing M14's partner identity).
Farms install modules; an Install records the link. Each module carries a
revenue-share percentage to Gitako, and a Payout aggregates what's owed —
disbursed through the shared payments seam. Listing + install + revenue-share
scaffold only; sandboxed third-party code execution is out of scope for v1.
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.farms.models import Farm
from apps.partners.models import Partner


class DeveloperModule(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_SUSPENDED, "Suspended"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    developer = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="modules")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    category = models.CharField(max_length=40, blank=True, help_text="vet, drone, soil_testing, …")
    description = models.TextField(blank=True)
    # Price the farm pays to install/use (kobo). 0 = free.
    price_kobo = models.BigIntegerField(default=0)
    # Gitako's cut of each paid install/usage (0–100).
    revenue_share_pct = models.PositiveSmallIntegerField(default=20)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} by {self.developer_id}"

    def gitako_cut_kobo(self) -> int:
        return self.price_kobo * self.revenue_share_pct // 100

    def developer_take_kobo(self) -> int:
        return self.price_kobo - self.gitako_cut_kobo()


class ModuleInstall(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(DeveloperModule, on_delete=models.CASCADE, related_name="installs")
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="module_installs")
    is_active = models.BooleanField(default=True)
    # Snapshot of price + split at install time (terms can change later).
    price_kobo = models.BigIntegerField(default=0)
    gitako_cut_kobo = models.BigIntegerField(default=0)
    developer_take_kobo = models.BigIntegerField(default=0)
    payment_reference = models.CharField(max_length=128, blank=True)
    installed_at = models.DateTimeField(auto_now_add=True)
    uninstalled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["module", "farm"], name="uniq_module_install"),
        ]

    def __str__(self) -> str:
        return f"{self.module_id} @ {self.farm_id}"
