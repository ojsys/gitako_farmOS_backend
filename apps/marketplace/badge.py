"""Verified-seller badge (PRD M13).

A farm earns the badge by keeping consistent records — the PRD's signal that a
seller is real and trackable. We compute it from data the farm already
generates, so it can't be self-asserted:

  - has at least one completed-or-active enterprise, AND
  - has logged a minimum number of activities, AND
  - has at least one financial transaction recorded.

Thresholds are intentionally modest for the closed beta and live here so they're
easy to tune without touching callers.
"""
from __future__ import annotations

from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.finance.models import Transaction

MIN_ACTIVITIES = 10


def is_verified_seller(farm) -> bool:
    has_enterprise = Enterprise.objects.filter(
        farm=farm, deleted_at__isnull=True,
        lifecycle_state__in=["active", "completed"],
    ).exists()
    if not has_enterprise:
        return False
    activity_count = Activity.objects.filter(
        tenant_id=farm.id, deleted_at__isnull=True,
    ).count()
    if activity_count < MIN_ACTIVITIES:
        return False
    has_finance = Transaction.objects.filter(
        tenant_id=farm.id, deleted_at__isnull=True,
    ).exists()
    return has_finance
