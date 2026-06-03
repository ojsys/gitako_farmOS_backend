"""Marketplace v1 — produce/livestock listings (PRD M13).

Scope per the PRD: "Farms can list produce/livestock for sale. Buyers
(registered Parties) can browse and contact. No on-platform clearing yet —
listing + connection only. Verified-seller badge for farms with consistent
records." Escrow/clearing is Phase 3 (M17).

A Listing is owned by a Farm (its tenant), but the browse surface is
**cross-tenant** by design — any authenticated user can see active listings
from all farms. Write access stays farm-scoped (owners/managers of the listing's
farm only).
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.farms.models import Farm


class Listing(models.Model):
    KIND_PRODUCE = "produce"
    KIND_LIVESTOCK = "livestock"
    KIND_INPUT = "input"
    KIND_OTHER = "other"
    KIND_CHOICES = [
        (KIND_PRODUCE, "Produce"),
        (KIND_LIVESTOCK, "Livestock"),
        (KIND_INPUT, "Farm input"),
        (KIND_OTHER, "Other"),
    ]

    STATUS_ACTIVE = "active"
    STATUS_SOLD = "sold"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_SOLD, "Sold"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="listings")
    title = models.CharField(max_length=160)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_PRODUCE)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=24, blank=True, help_text="bags, kg, birds, crates…")
    price_kobo = models.BigIntegerField(default=0, help_text="Asking price in kobo (per unit or lot).")
    price_is_per_unit = models.BooleanField(default=True)
    region = models.CharField(max_length=64, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    photo_keys = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["kind", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_kind_display()})"


# ---------- Marketplace v2 — escrow (PRD M17) ----------

class Offer(models.Model):
    """A buyer's offer against a listing. Buyer is a Gitako user (the farmer on
    the other side); accepting an offer creates a Contract."""

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_DECLINED, "Declined"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="offers")
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers_made",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    offer_price_kobo = models.BigIntegerField(help_text="Total offered amount in kobo.")
    message = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Offer {self.offer_price_kobo} on {self.listing_id} ({self.status})"


class Contract(models.Model):
    """An accepted deal moving through escrow.

    State machine:
      agreed → funded → delivered → released   (happy path)
                       ↘ disputed → released | refunded
                       ↘ cancelled
    """

    STATE_AGREED = "agreed"        # offer accepted; awaiting buyer funding
    STATE_FUNDED = "funded"        # escrow holds buyer's money
    STATE_DELIVERED = "delivered"  # seller marked delivered; QA pending
    STATE_RELEASED = "released"    # funds released to seller (deal complete)
    STATE_DISPUTED = "disputed"    # QA failed / buyer raised an issue
    STATE_REFUNDED = "refunded"    # escrow returned to buyer
    STATE_CANCELLED = "cancelled"
    STATE_CHOICES = [
        (STATE_AGREED, "Agreed"),
        (STATE_FUNDED, "Funded (in escrow)"),
        (STATE_DELIVERED, "Delivered"),
        (STATE_RELEASED, "Released"),
        (STATE_DISPUTED, "Disputed"),
        (STATE_REFUNDED, "Refunded"),
        (STATE_CANCELLED, "Cancelled"),
    ]

    QA_PENDING = "pending"
    QA_PASSED = "passed"
    QA_FAILED = "failed"
    QA_CHOICES = [(QA_PENDING, "Pending"), (QA_PASSED, "Passed"), (QA_FAILED, "Failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offer = models.OneToOneField(Offer, on_delete=models.PROTECT, related_name="contract")
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="contracts")
    seller_farm = models.ForeignKey(Farm, on_delete=models.PROTECT, related_name="sales_contracts")
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_contracts",
    )
    amount_kobo = models.BigIntegerField()
    state = models.CharField(max_length=12, choices=STATE_CHOICES, default=STATE_AGREED)
    qa_result = models.CharField(max_length=8, choices=QA_CHOICES, default=QA_PENDING)
    qa_notes = models.TextField(blank=True)
    # Payment provider references for the escrow legs.
    charge_reference = models.CharField(max_length=128, blank=True)
    release_reference = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Contract {self.id} ({self.state})"
