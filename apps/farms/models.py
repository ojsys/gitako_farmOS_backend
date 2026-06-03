"""Farm, StaffMembership, and Party models — the identity layer above tenancy.

A `Farm` is the tenant unit. Its `id` IS the tenant_id used everywhere else.
StaffMembership ties users to farms with roles. Party is any external person /
organization the farm interacts with.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel, uuid7


class Farm(models.Model):
    """A farm is itself a tenant root — its own `id` is the `tenant_id` for all
    its records. We don't extend TenantScopedModel here; this row defines the scope.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    name = models.CharField(max_length=120)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_farms"
    )
    # Location stored as plain coordinates + GeoJSON (no PostGIS dependency, so
    # the API runs on standard Postgres / shared hosting). The API still exposes
    # `location` as {lat, lng} and `boundary` as a GeoJSON geometry.
    location_lat = models.FloatField(null=True, blank=True)
    location_lng = models.FloatField(null=True, blank=True)
    boundary_geojson = models.JSONField(null=True, blank=True)
    address_text = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=64, blank=True)
    modules_enabled = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    client_seq = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.id


class StaffMembership(models.Model):
    """User membership in a farm. Role-based permissions per PRD M1."""

    ROLE_OWNER = "owner"
    ROLE_MANAGER = "manager"
    ROLE_FIELD = "field_staff"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_MANAGER, "Manager"),
        (ROLE_FIELD, "Field staff"),
        (ROLE_VIEWER, "Viewer"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    permissions_json = models.JSONField(default=dict)
    invited_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "farm"], name="uniq_user_farm")
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.farm_id}={self.role}"


class Party(TenantScopedModel):
    KIND_CHOICES = [
        ("supplier", "Supplier"),
        ("buyer", "Buyer"),
        ("vet", "Vet"),
        ("officer", "Extension officer"),
        ("financier", "Financier"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    contact_json = models.JSONField(default=dict)
    nin_bvn = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name_plural = "Parties"

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"
