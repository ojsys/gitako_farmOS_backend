"""Allow-list of tables eligible for sync.

Only tables registered here can be mutated via the sync endpoints. Each entry
maps the table name (matches model._meta.db_table) to the Django model and a
serializer that turns row JSON into a model instance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import models


@dataclass(frozen=True)
class SyncTable:
    model: type[models.Model]
    # Fields the device is allowed to write. Server-managed fields (id, tenant_id,
    # created_at, updated_at, deleted_at, client_seq) are handled separately.
    writable_fields: tuple[str, ...]


REGISTRY: dict[str, SyncTable] = {}


def register(table_name: str, model: type[models.Model], writable_fields: tuple[str, ...]) -> None:
    REGISTRY[table_name] = SyncTable(model=model, writable_fields=writable_fields)


def get(table_name: str) -> SyncTable | None:
    return REGISTRY.get(table_name)


def all_tables() -> dict[str, SyncTable]:
    return dict(REGISTRY)


def serialize_row(instance: models.Model) -> dict[str, Any]:
    """Server-canonical JSON snapshot of a row, written into ChangeLog payload
    and returned to the client.
    """
    out: dict[str, Any] = {}
    for f in instance._meta.fields:
        val = getattr(instance, f.attname, None)
        if val is None:
            out[f.attname] = None
        elif hasattr(val, "isoformat"):  # datetime / date
            out[f.attname] = val.isoformat()
        else:
            out[f.attname] = str(val) if not isinstance(val, (int, float, bool, dict, list, str)) else val
    return out
