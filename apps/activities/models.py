"""Activity — anything that happens on a farm.

Phase 1 activity types (PRD M2/M3):
  Crops:  land_prep, planting, fertilizing, spraying, weeding, irrigation,
          scouting, harvesting, sale
  Flock:  feed, water, vaccinate, medicate, mortality, weigh, eggs, sale

Type is free-form text (we won't enum-lock new types) but the mobile app
picks from a known palette. `attrs` carries the type-specific payload.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.enterprises.models import Enterprise
from apps.tenancy.models import TenantScopedModel


class Activity(TenantScopedModel):
    # Weather is stamped on every activity so we can correlate outcomes
    # (yield, mortality, FCR) with conditions at the time without scraping
    # external sources. Three buckets is the right resolution for the field —
    # finer-grained weather (mm/min) lands later via a partner API.
    WEATHER_JUST_RAINED = "just_rained"
    WEATHER_ABOUT_TO_RAIN = "about_to_rain"
    WEATHER_CLEAR = "clear"
    WEATHER_CHOICES = [
        (WEATHER_JUST_RAINED, "Just rained"),
        (WEATHER_ABOUT_TO_RAIN, "About to rain"),
        (WEATHER_CLEAR, "Clear · no rain expected"),
    ]

    enterprise = models.ForeignKey(
        Enterprise, on_delete=models.CASCADE, related_name="activities"
    )
    type = models.CharField(max_length=32)
    # `actor_user` = who recorded it (server-stamped from request.user).
    # `performed_by` = who physically did the work (can differ — owner records
    # on behalf of field staff). Defaults to actor_user when not specified.
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name="recorded_activities",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="performed_activities",
        help_text="Who physically did the work (may differ from the recorder).",
    )
    occurred_at = models.DateTimeField(db_index=True)
    weather = models.CharField(
        max_length=16, choices=WEATHER_CHOICES, blank=True,
        help_text="Conditions when the activity happened.",
    )
    # GPS stored as plain lat/lng (no PostGIS). API still exposes `gps_point`
    # as {lat, lng}.
    gps_lat = models.FloatField(null=True, blank=True)
    gps_lng = models.FloatField(null=True, blank=True)
    photo_keys = models.JSONField(default=list)
    cost_kobo = models.BigIntegerField(default=0)
    notes = models.TextField(blank=True)
    attrs = models.JSONField(default=dict)
    # attrs examples:
    #   {"inputs": [{"item_id": "...", "qty": 3, "unit": "bags"}], "harvest_kg": 1200}

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approved_activities",
    )

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["enterprise", "-occurred_at"])]

    def __str__(self) -> str:
        return f"{self.type} on {self.occurred_at:%Y-%m-%d}"
