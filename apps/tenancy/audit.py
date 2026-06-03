"""Helpers for writing audit entries from model save/delete.

Use `record_audit(...)` from within a service / view layer. We don't auto-wire
signals on every model because audit should be intentional for finance and PII.
"""
from __future__ import annotations

import uuid
from typing import Any

from django.forms.models import model_to_dict

from .models import AuditEntry


def serialize(instance) -> dict[str, Any]:
    if instance is None:
        return {}
    data = model_to_dict(instance)
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in data.items()}


def record_audit(
    *,
    actor_user,
    instance,
    action: str,
    before=None,
    tenant_id: uuid.UUID | None = None,
) -> AuditEntry:
    return AuditEntry.objects.create(
        actor_user=actor_user if getattr(actor_user, "is_authenticated", False) else None,
        target_table=instance._meta.db_table,
        target_id=instance.pk,
        action=action,
        before_json=serialize(before),
        after_json=serialize(instance),
        tenant_id=tenant_id or getattr(instance, "tenant_id", None),
    )
