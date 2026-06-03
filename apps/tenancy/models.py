"""Tenant scoping primitives.

The PRD picks **single-DB, tenant_id on every row** for v1 (PRD §6 Multi-tenancy).
A `tenant` here is a Farm — when a user has multiple farms (P1 owners with several
operations), each farm is its own tenant scope. Cross-tenant queries are explicit.

Every domain model (Enterprise, Activity, Inventory, Transaction, …) extends
`TenantScopedModel` and is filtered through the request's active tenant by
`TenantMiddleware` + the model managers.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


def uuid7() -> uuid.UUID:
    """UUIDv7 — time-ordered for index locality.

    Falls back to uuid4 on Python <3.14 (uuid.uuid7 added in 3.14). Both are valid
    UUIDs; the field type is the same so this is safe.
    """
    if hasattr(uuid, "uuid7"):
        return uuid.uuid7()
    return uuid.uuid4()


class TenantScopedQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def for_tenant(self, tenant_id):
        return self.filter(tenant_id=tenant_id)


class TenantScopedManager(models.Manager):
    def get_queryset(self) -> TenantScopedQuerySet:
        return TenantScopedQuerySet(self.model, using=self._db).filter(deleted_at__isnull=True)

    def with_deleted(self) -> TenantScopedQuerySet:
        return TenantScopedQuerySet(self.model, using=self._db)


class TenantScopedModel(models.Model):
    """Abstract base for any record that belongs to a tenant (= a Farm).

    Conventions enforced here:
    - UUIDv7 primary keys (client-generatable, time-ordered)
    - tenant_id on every row, indexed
    - soft delete via deleted_at (tombstone for sync)
    - updated_at drives last-write-wins on the sync layer
    - client_seq carries the device's local sequence number for the last write
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    client_seq = models.BigIntegerField(default=0)

    objects = TenantScopedManager()
    all_objects = TenantScopedQuerySet.as_manager()

    class Meta:
        abstract = True


class AuditEntry(models.Model):
    """Append-only audit trail for finance and PII mutations (PRD non-functional).

    Never deleted, never edited. Queryable by target_table + target_id.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    target_table = models.CharField(max_length=64)
    target_id = models.UUIDField()
    action = models.CharField(max_length=16)
    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)
    tenant_id = models.UUIDField(db_index=True, null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["target_table", "target_id", "-at"])]

    def __str__(self) -> str:
        return f"{self.target_table}:{self.target_id} {self.action} by {self.actor_user_id}"
