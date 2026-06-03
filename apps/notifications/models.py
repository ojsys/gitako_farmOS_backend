"""Notifications & reminders (PRD M8).

Three models:
- **NotificationRule** — per-farm threshold config (mortality spike, low stock,
  overdue activity). Absent rules fall back to sensible defaults, so the engine
  works before anyone touches settings.
- **Notification** — an in-app feed item for one recipient. Idempotent on
  (user, dedupe_key) so the schedulers can run repeatedly without spamming.
- **DigestPreference** — when a user wants their daily summary.

Delivery is in-app (polled by clients) + SMS for critical alerts — there is no
push provider, so no device-token registry. These are server-owned operational
records, not part of the offline sync set, so they're plain models rather than
TenantScopedModel.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.farms.models import Farm


class NotificationRule(models.Model):
    """Per-farm alert thresholds. One row per (farm, rule_type)."""

    RULE_MORTALITY = "mortality_spike"
    RULE_LOW_STOCK = "low_stock"
    RULE_OVERDUE = "overdue_activity"
    RULE_CHOICES = [
        (RULE_MORTALITY, "Mortality spike"),
        (RULE_LOW_STOCK, "Low stock"),
        (RULE_OVERDUE, "Overdue activity"),
    ]

    # Defaults applied when a farm has no explicit rule row.
    DEFAULTS = {
        RULE_MORTALITY: {"enabled": True, "params": {"pct": 5.0}, "critical": True},
        RULE_LOW_STOCK: {"enabled": True, "params": {}, "critical": False},
        RULE_OVERDUE: {"enabled": True, "params": {"grace_days": 0}, "critical": False},
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="notification_rules")
    rule_type = models.CharField(max_length=32, choices=RULE_CHOICES)
    enabled = models.BooleanField(default=True)
    # Threshold params, e.g. {"pct": 5.0} for mortality.
    params = models.JSONField(default=dict, blank=True)
    # Channels to fan out on, e.g. ["in_app", "push", "sms"].
    channels = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["farm", "rule_type"], name="uniq_rule_per_farm"),
        ]

    def __str__(self) -> str:
        return f"{self.get_rule_type_display()} @ {self.farm_id}"


class Notification(models.Model):
    """An in-app notification for a single recipient."""

    TYPE_CALENDAR = "calendar_reminder"
    TYPE_MORTALITY = "mortality_spike"
    TYPE_LOW_STOCK = "low_stock"
    TYPE_OVERDUE = "overdue_activity"
    TYPE_DIGEST = "daily_digest"
    TYPE_CUSTOM = "custom"
    TYPE_CHOICES = [
        (TYPE_CALENDAR, "Calendar reminder"),
        (TYPE_MORTALITY, "Mortality spike"),
        (TYPE_LOW_STOCK, "Low stock"),
        (TYPE_OVERDUE, "Overdue activity"),
        (TYPE_DIGEST, "Daily digest"),
        (TYPE_CUSTOM, "Custom"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications",
    )
    tenant_id = models.UUIDField(db_index=True, null=True, blank=True)
    type = models.CharField(max_length=32, choices=TYPE_CHOICES, default=TYPE_CUSTOM)
    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    # Idempotency key — the schedulers run on a cron, so a stable key per logical
    # event keeps repeated runs from creating duplicates.
    dedupe_key = models.CharField(max_length=200)
    channels_sent = models.JSONField(default=list, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "dedupe_key"], name="uniq_notification_dedupe"),
        ]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.type} → {self.user_id}: {self.title}"


class DigestPreference(models.Model):
    """Per-user daily-summary preference."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="digest_preference",
    )
    enabled = models.BooleanField(default=True)
    # Hour of day (0-23) in the project timezone to send the digest.
    send_hour = models.PositiveSmallIntegerField(default=18)
    last_sent_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"digest for {self.user_id} @ {self.send_hour}:00"
