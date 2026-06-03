"""Public API + Partner Portal (PRD M14).

An ecosystem partner (bank, insurer, supplier, off-taker) authenticates with an
API key and reads farm data **only** for farms that have explicitly granted them
consent, and only within the scopes the farm allowed. Consent is per (partner,
farm); the farmer can revoke at any time (PRD privacy requirement).

Models:
- **Partner** — the organization. Holds rate-limit tier + webhook secret.
- **ApiKey** — a credential for a partner. We store only a SHA-256 hash; the raw
  key is shown once at creation.
- **ConsentGrant** — (partner, farm, scopes[]) with an active flag. The farmer's
  switch controlling what a partner can see.
- **PartnerAuditEntry** — append-only log of every partner API read.

Scopes (granular consent, PRD): registry, aggregate, activity_events.
"""
from __future__ import annotations

import uuid

from django.db import models

from apps.farms.models import Farm

SCOPE_REGISTRY = "registry"        # farm name, region, modules, owner contact
SCOPE_AGGREGATE = "aggregate"      # anonymized rollups: counts, totals, no row detail
SCOPE_ACTIVITY = "activity_events" # activity stream (type + timestamp, no notes/photos)
SCOPE_CREDIT = "credit_score"      # farm credit score + band (M16)
SCOPE_CHOICES = [
    (SCOPE_REGISTRY, "Farm registry"),
    (SCOPE_AGGREGATE, "Aggregate data"),
    (SCOPE_ACTIVITY, "Activity events"),
    (SCOPE_CREDIT, "Credit score"),
]
ALL_SCOPES = {SCOPE_REGISTRY, SCOPE_AGGREGATE, SCOPE_ACTIVITY, SCOPE_CREDIT}


class Partner(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    kind = models.CharField(
        max_length=24,
        choices=[("bank", "Bank / MFI"), ("insurer", "Insurer"),
                 ("supplier", "Supplier"), ("offtaker", "Off-taker"), ("other", "Other")],
        default="other",
    )
    contact_email = models.EmailField(blank=True)
    rate_limit_per_min = models.PositiveIntegerField(default=60)
    webhook_secret = models.CharField(max_length=64, blank=True, help_text="HMAC secret for signed webhooks.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class ApiKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="api_keys")
    prefix = models.CharField(max_length=12, db_index=True, help_text="First chars of the key, for lookup + display.")
    key_hash = models.CharField(max_length=64, help_text="SHA-256 of the full key. Raw key never stored.")
    label = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["prefix", "is_active"])]

    def __str__(self) -> str:
        return f"{self.partner.name} key …{self.prefix}"


class ConsentGrant(models.Model):
    """A farm's grant of data access to a partner, scoped + revocable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="consents")
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="partner_consents")
    scopes = models.JSONField(default=list, help_text="Subset of registry|aggregate|activity_events.")
    is_active = models.BooleanField(default=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["partner", "farm"], name="uniq_consent_partner_farm"),
        ]

    def allows(self, scope: str) -> bool:
        return self.is_active and scope in (self.scopes or [])

    def __str__(self) -> str:
        return f"{self.farm_id} → {self.partner_id} ({'active' if self.is_active else 'revoked'})"


class PartnerAuditEntry(models.Model):
    """Append-only record of partner API reads (PRD: audit log)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="audit_entries")
    path = models.CharField(max_length=255)
    farm = models.ForeignKey(Farm, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    scope = models.CharField(max_length=24, blank=True)
    status_code = models.PositiveSmallIntegerField(default=200)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["partner", "-at"])]
