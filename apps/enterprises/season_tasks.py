"""Materialize the GAP calendar into persistent, assignable SeasonTasks.

`ensure_season_tasks(enterprise)` turns the enterprise's template (anchored on
its planting/stocking/acquisition date) into stored SeasonTask rows. It's
idempotent — keyed on (enterprise, slot_key) — so it's safe to call on
creation, on planting-date change, or lazily on first task list.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction as db_transaction
from django.utils import timezone

from .calendar import anchor_date, template_for
from .models import Enterprise, SeasonTask


def _slot_key(activity_type: str, target_date) -> str:
    return f"{activity_type}:{target_date.isoformat()}"


@db_transaction.atomic
def ensure_season_tasks(enterprise: Enterprise) -> list[SeasonTask]:
    """Create any missing SeasonTasks for the enterprise from its GAP template.

    Returns the full current task list. Existing tasks (and their assignment /
    completion state) are never disturbed; only missing slots are added. Slots
    whose anchor date moved are reconciled by `regenerate_season_tasks`.
    """
    template, source = template_for(enterprise)
    anchor = anchor_date(enterprise)
    if not template or anchor is None:
        return list(enterprise.season_tasks.all())

    existing = {t.slot_key: t for t in enterprise.season_tasks.all()}
    to_create = []
    for entry in template:
        target = anchor + timedelta(days=entry.day_offset)
        key = _slot_key(entry.activity_type, target)
        if key in existing:
            continue
        to_create.append(SeasonTask(
            tenant_id=enterprise.tenant_id,
            enterprise=enterprise,
            activity_type=entry.activity_type,
            label=entry.label,
            notes=entry.notes,
            target_date=target,
            source=source,
            slot_key=key,
        ))
    if to_create:
        SeasonTask.objects.bulk_create(to_create)
    return list(enterprise.season_tasks.all())


@db_transaction.atomic
def regenerate_season_tasks(enterprise: Enterprise) -> list[SeasonTask]:
    """Rebuild the schedule after a planting-date (or variety) change.

    Pending, unassigned tasks are replaced wholesale. Tasks that are already
    done, skipped, or assigned are preserved — we don't silently throw away a
    farm hand's work or an assignment when the date shifts.
    """
    enterprise.season_tasks.filter(
        status=SeasonTask.STATUS_PENDING, assigned_to__isnull=True,
    ).delete()
    return ensure_season_tasks(enterprise)


def complete_task_from_activity(activity) -> SeasonTask | None:
    """Mark the matching pending SeasonTask done when a farm hand logs an
    activity. Matches by enterprise + activity_type + nearest target within a
    ±5-day window (same tolerance as the synth calendar). Returns the task it
    completed, or None."""
    if activity.enterprise_id is None:
        return None
    occurred = activity.occurred_at.date() if activity.occurred_at else timezone.localdate()
    window = timedelta(days=5)
    candidates = SeasonTask.objects.filter(
        enterprise_id=activity.enterprise_id,
        activity_type=activity.type,
        status=SeasonTask.STATUS_PENDING,
        target_date__gte=occurred - window,
        target_date__lte=occurred + window,
    ).order_by("target_date")
    # Nearest target to the activity date.
    task = min(
        candidates,
        key=lambda t: abs((t.target_date - occurred).days),
        default=None,
    )
    if task is None:
        return None
    task.status = SeasonTask.STATUS_DONE
    task.completed_at = timezone.now()
    task.completed_activity = activity
    task.save(update_fields=["status", "completed_at", "completed_activity", "updated_at"])
    return task
