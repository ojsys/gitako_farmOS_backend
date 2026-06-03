"""Sync push/pull engine.

Pure functions over Django models. Side effects are confined to writes against
the registered tables + the ChangeLog. Callers wrap in a transaction.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import registry
from .models import ChangeLog


@dataclass
class PushOp:
    table: str
    row_id: uuid.UUID
    op: str  # 'insert' | 'update' | 'delete'
    payload: dict[str, Any]
    client_seq: int
    base_updated_at: datetime | None


@dataclass
class AcceptedOp:
    row_id: uuid.UUID
    server_seq: int


@dataclass
class ConflictOp:
    row_id: uuid.UUID
    server_payload: dict[str, Any]
    client_payload: dict[str, Any]


def _next_server_seq(tenant_id: uuid.UUID) -> int:
    """Allocate the next per-tenant server_seq.

    Uses pg_advisory_xact_lock to serialize allocation per tenant inside the
    current transaction, then takes max+1 from the existing ChangeLog rows.
    Adequate at our scale; can be promoted to a per-tenant sequence later.
    """
    with connection.cursor() as cur:
        # Hash the UUID to a bigint for advisory_lock
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [str(tenant_id)])
    current = (
        ChangeLog.objects.filter(tenant_id=tenant_id)
        .order_by("-server_seq")
        .values_list("server_seq", flat=True)
        .first()
    )
    return (current or 0) + 1


def _apply_op(
    *,
    op: PushOp,
    tenant_id: uuid.UUID,
    actor_user,
    device_id: str,
) -> tuple[AcceptedOp | None, ConflictOp | None]:
    from apps.tenancy.permissions import (
        assert_can_create,
        assert_can_modify,
        role_for,
    )

    entry = registry.get(op.table)
    if entry is None:
        # Table the server doesn't sync (obsolete client table, or a newer
        # client than this server). Acknowledge as a no-op so the client drops
        # it from its outbox — a single such op must never 400 the whole batch
        # and wedge all syncing. Symmetric with pull's "skip unknown table".
        return AcceptedOp(op.row_id, server_seq=0), None
    Model = entry.model
    existing = Model.all_objects.filter(pk=op.row_id).first()  # includes deleted
    role = role_for(actor_user, tenant_id)

    if op.op == "insert":
        if existing is not None:
            # Treat as idempotent: if same client_seq, no-op. Otherwise treat as update.
            if existing.client_seq == op.client_seq:
                return AcceptedOp(op.row_id, server_seq=0), None
            assert_can_modify(role, instance=existing, user=actor_user, table=op.table)
            return _apply_update(op=op, existing=existing, entry=entry, actor_user=actor_user,
                                 tenant_id=tenant_id, device_id=device_id)
        assert_can_create(role, op.table)
        return _apply_insert(op=op, entry=entry, actor_user=actor_user,
                             tenant_id=tenant_id, device_id=device_id)

    if op.op == "update":
        if existing is None:
            assert_can_create(role, op.table)
            return _apply_insert(op=op, entry=entry, actor_user=actor_user,
                                 tenant_id=tenant_id, device_id=device_id)
        assert_can_modify(role, instance=existing, user=actor_user, table=op.table)
        return _apply_update(op=op, existing=existing, entry=entry, actor_user=actor_user,
                             tenant_id=tenant_id, device_id=device_id)

    if op.op == "delete":
        if existing is None:
            return AcceptedOp(op.row_id, server_seq=0), None
        assert_can_modify(role, instance=existing, user=actor_user, table=op.table)
        existing.deleted_at = timezone.now()
        existing.client_seq = op.client_seq
        existing.save(update_fields=["deleted_at", "client_seq", "updated_at"])
        server_seq = _write_changelog(
            op="delete", instance=existing, tenant_id=tenant_id,
            actor_user=actor_user, device_id=device_id, payload={},
        )
        return AcceptedOp(op.row_id, server_seq), None

    raise ValueError(f"Unknown op: {op.op}")


def _fk_attname(model, field_name: str) -> str:
    """Return the column-level attname for a model field.

    For FKs Django wants `<field>_id` (raw value), not `<field>` (instance).
    For plain fields the attname == name. Lets the sync layer accept the
    field name the REST API uses while writing the right attribute server-side.
    """
    try:
        return model._meta.get_field(field_name).attname
    except Exception:
        return field_name


def _apply_insert(*, op, entry, actor_user, tenant_id, device_id):
    Model = entry.model
    kwargs = {"id": op.row_id, "tenant_id": tenant_id, "client_seq": op.client_seq}
    for f in entry.writable_fields:
        if f in op.payload:
            kwargs[_fk_attname(Model, f)] = op.payload[f]
    # For tables that track the recorder, always stamp the request user — we
    # don't trust the client to declare who created the row. Powers the
    # "field-staff can only edit their own" rule.
    field_names = {f.name for f in Model._meta.fields}
    if "actor_user" in field_names:
        kwargs["actor_user_id"] = getattr(actor_user, "id", None)
    # Default `performed_by` to the recorder when the client didn't send one.
    if "performed_by" in field_names and "performed_by_id" not in kwargs:
        kwargs["performed_by_id"] = getattr(actor_user, "id", None)
    instance = Model.objects.create(**kwargs)
    payload = registry.serialize_row(instance)
    server_seq = _write_changelog(
        op="insert", instance=instance, tenant_id=tenant_id,
        actor_user=actor_user, device_id=device_id, payload=payload,
    )
    return AcceptedOp(op.row_id, server_seq), None


def _apply_update(*, op, existing, entry, actor_user, tenant_id, device_id):
    # Conflict check: did the server move on since the client's base point?
    if op.base_updated_at and existing.updated_at > op.base_updated_at:
        server_payload = registry.serialize_row(existing)
        return None, ConflictOp(
            row_id=op.row_id,
            server_payload=server_payload,
            client_payload=op.payload,
        )

    Model = type(existing)
    for f in entry.writable_fields:
        if f in op.payload:
            setattr(existing, _fk_attname(Model, f), op.payload[f])
    existing.client_seq = op.client_seq
    if existing.deleted_at is not None and op.op == "update":
        # Resurrecting a tombstoned row via update is allowed; client_seq wins.
        existing.deleted_at = None
    existing.save()
    payload = registry.serialize_row(existing)
    server_seq = _write_changelog(
        op="update", instance=existing, tenant_id=tenant_id,
        actor_user=actor_user, device_id=device_id, payload=payload,
    )
    return AcceptedOp(op.row_id, server_seq), None


def _write_changelog(*, op, instance, tenant_id, actor_user, device_id, payload) -> int:
    server_seq = _next_server_seq(tenant_id)
    ChangeLog.objects.create(
        tenant_id=tenant_id,
        server_seq=server_seq,
        table=instance._meta.db_table,
        row_id=instance.pk,
        op=op,
        payload=payload,
        actor_user=actor_user if getattr(actor_user, "is_authenticated", False) else None,
        device_id=device_id,
        client_seq=getattr(instance, "client_seq", 0),
    )
    return server_seq


def push_batch(
    *,
    ops: list[PushOp],
    tenant_id: uuid.UUID,
    actor_user,
    device_id: str,
) -> tuple[list[AcceptedOp], list[ConflictOp]]:
    accepted: list[AcceptedOp] = []
    conflicts: list[ConflictOp] = []
    with transaction.atomic():
        for op in ops:
            acc, conf = _apply_op(
                op=op, tenant_id=tenant_id, actor_user=actor_user, device_id=device_id
            )
            if acc is not None:
                accepted.append(acc)
            if conf is not None:
                conflicts.append(conf)
    return accepted, conflicts


def pull_changes(*, tenant_id: uuid.UUID, since: int, limit: int = 500) -> dict:
    qs = (
        ChangeLog.objects.filter(tenant_id=tenant_id, server_seq__gt=since)
        .order_by("server_seq")[: limit + 1]
    )
    rows = list(qs)
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_since = rows[-1].server_seq if rows else since
    return {
        "changes": [
            {
                "server_seq": r.server_seq,
                "table": r.table,
                "row_id": str(r.row_id),
                "op": r.op,
                "payload": r.payload,
                "client_seq": r.client_seq,
            }
            for r in rows
        ],
        "next_since": next_since,
        "has_more": has_more,
    }


def parse_push_body(body: dict) -> list[PushOp]:
    ops: list[PushOp] = []
    for raw in body.get("ops", []):
        ops.append(
            PushOp(
                table=raw["table"],
                row_id=uuid.UUID(raw["row_id"]),
                op=raw["op"],
                payload=raw.get("payload", {}),
                client_seq=int(raw.get("client_seq", 0)),
                base_updated_at=parse_datetime(raw["base_updated_at"])
                if raw.get("base_updated_at")
                else None,
            )
        )
    return ops
