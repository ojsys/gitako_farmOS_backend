"""Sync log + cursor + toy spike models.

The `ChangeLog` and `SyncCursor` here are the real sync data plane.
`SyncNote` and `SyncTag` are tiny toy tables wired into the sync allow-list so
we can exercise the push/pull/conflict protocol end-to-end before the real
domain models (Activity, Inventory…) land.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.tenancy.models import TenantScopedModel, uuid7


class ChangeLog(models.Model):
    OP_INSERT = "insert"
    OP_UPDATE = "update"
    OP_DELETE = "delete"
    OP_CHOICES = [(OP_INSERT, "Insert"), (OP_UPDATE, "Update"), (OP_DELETE, "Delete")]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    server_seq = models.BigIntegerField(db_index=True)
    table = models.CharField(max_length=64)
    row_id = models.UUIDField()
    op = models.CharField(max_length=8, choices=OP_CHOICES)
    payload = models.JSONField(default=dict)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    device_id = models.CharField(max_length=64, blank=True)
    client_seq = models.BigIntegerField(default=0)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "server_seq"]),
            models.Index(fields=["table", "row_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "server_seq"], name="uniq_changelog_tenant_seq"
            )
        ]
        ordering = ["server_seq"]


class SyncCursor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sync_cursors"
    )
    tenant_id = models.UUIDField(db_index=True)
    device_id = models.CharField(max_length=64)
    last_server_seq_acked = models.BigIntegerField(default=0)
    last_pull_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tenant_id", "device_id"], name="uniq_cursor_user_tenant_device"
            )
        ]


# ---------- Spike: toy tables to exercise the protocol ----------

class SyncNote(TenantScopedModel):
    """Toy table to prove the sync layer end-to-end. Real models replace this."""

    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)

    class Meta:
        db_table = "sync_note"


class SyncTag(TenantScopedModel):
    """Second toy table for testing multi-table sync ordering."""

    name = models.CharField(max_length=64)
    color = models.CharField(max_length=16, default="green")

    class Meta:
        db_table = "sync_tag"
