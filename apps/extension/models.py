"""Extension Officer / Vet workflows (PRD M15).

An extension officer or vet is a Gitako user who works across many farms. Per
the PRD: "Multi-farm access for officers (with farmer consent); issue
advisories, schedule visits, record interventions; officer-to-farm messaging;
aggregate reports for ADPs and NGOs."

Models:
- **OfficerAccess** — (officer, farm) consent link, farmer-approved. The
  boundary that lets an officer read/advise a farm they're not a staff member of.
- **Advisory** — guidance an officer issues to a farm.
- **Visit** — a scheduled or recorded farm visit / intervention.

Officer access is its own consent surface (distinct from StaffMembership, which
is for people who work *on* the farm, and from partner ConsentGrant, which is
for organizations consuming the API).
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.farms.models import Farm


class OfficerAccess(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_REVOKED = "revoked"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_REVOKED, "Revoked"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="officer_access",
    )
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="officer_access")
    # Free-text program affiliation (e.g. "Oyo State ADP", "Sasakawa").
    program = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["officer", "farm"], name="uniq_officer_farm"),
        ]

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_ACTIVE

    def __str__(self) -> str:
        return f"{self.officer_id} → {self.farm_id} ({self.status})"


class Advisory(models.Model):
    SEVERITY_CHOICES = [("info", "Info"), ("action", "Action needed"), ("urgent", "Urgent")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="advisories",
    )
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="advisories")
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    severity = models.CharField(max_length=12, choices=SEVERITY_CHOICES, default="info")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} → {self.farm_id}"


class Visit(models.Model):
    STATUS_SCHEDULED = "scheduled"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="visits",
    )
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="visits")
    scheduled_for = models.DateField()
    purpose = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    intervention_notes = models.TextField(blank=True, help_text="Recorded after the visit.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-scheduled_for"]

    def __str__(self) -> str:
        return f"Visit {self.farm_id} on {self.scheduled_for} ({self.status})"
