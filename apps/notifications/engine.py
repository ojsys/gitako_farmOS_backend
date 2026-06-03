"""Notification engine — the logic the Celery tasks wrap.

Kept free of Celery so it can be unit-tested directly with @pytest.mark.django_db.
Each function scans farms, decides what to notify, and calls dispatch.notify()
with a stable dedupe_key so repeated runs are idempotent.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.utils import timezone

from apps.enterprises.calendar import planned_tasks_for_farm
from apps.enterprises.metrics import metrics_for
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm
from apps.inventory.models import InventoryItem
from apps.inventory.serializers import _stock_qty

from .dispatch import CHANNEL_IN_APP, farm_alert_recipients, notify
from .models import DigestPreference, Notification, NotificationRule
from .rules import effective_rule

log = logging.getLogger("gitako.notifications")


def _live_farms():
    return Farm.objects.filter(deleted_at__isnull=True)


def run_calendar_reminders(*, window_days: int = 2, today: date | None = None) -> int:
    """Remind owners/managers of pending calendar tasks due within `window_days`."""
    today = today or timezone.localdate()
    horizon = today + timedelta(days=window_days)
    created = 0
    for farm in _live_farms():
        recipients = farm_alert_recipients(farm)
        if not recipients:
            continue
        for task in planned_tasks_for_farm(farm, window_from=today, window_to=horizon):
            if task["status"] != "pending":
                continue
            target = date.fromisoformat(task["target_date"])
            if target < today or target > horizon:
                continue
            dedupe = f"calendar:{task['enterprise_id']}:{task['activity_type']}:{task['target_date']}"
            for user in recipients:
                res = notify(
                    user=user,
                    type=Notification.TYPE_CALENDAR,
                    title=f"Upcoming: {task['label']}",
                    body=f"{task['enterprise_name']} — due {task['target_date']}.",
                    dedupe_key=dedupe,
                    tenant_id=farm.id,
                    data={"enterprise_id": task["enterprise_id"], "kind": task["source"]},
                    channels=(CHANNEL_IN_APP,),
                )
                created += int(res.created)
    return created


def run_threshold_alerts(*, today: date | None = None) -> int:
    """Mortality spikes, low stock, and overdue activities."""
    today = today or timezone.localdate()
    created = 0
    for farm in _live_farms():
        recipients = farm_alert_recipients(farm)
        if not recipients:
            continue
        created += _mortality_alerts(farm, recipients, today)
        created += _low_stock_alerts(farm, recipients, today)
        created += _overdue_alerts(farm, recipients, today)
    return created


def _mortality_alerts(farm, recipients, today) -> int:
    rule = effective_rule(farm, NotificationRule.RULE_MORTALITY)
    if not rule.enabled:
        return 0
    threshold = float(rule.params.get("pct", 5.0))
    created = 0
    # Mortality applies to poultry flocks, livestock herds, and fish ponds.
    animal_enterprises = Enterprise.objects.filter(
        farm=farm,
        type__in=[Enterprise.TYPE_FLOCK, Enterprise.TYPE_HERD, Enterprise.TYPE_POND],
        lifecycle_state="active",
        deleted_at__isnull=True,
    )
    for ent in animal_enterprises:
        m = metrics_for(ent)
        if m.get("mortality_pct", 0) < threshold:
            continue
        dedupe = f"mortality:{ent.id}:{today.isoformat()}"
        for user in recipients:
            res = notify(
                user=user,
                type=Notification.TYPE_MORTALITY,
                title=f"Mortality spike: {ent.name}",
                body=f"Mortality at {m['mortality_pct']}% (alert above {threshold}%).",
                dedupe_key=dedupe,
                tenant_id=farm.id,
                data={"enterprise_id": str(ent.id), "mortality_pct": m["mortality_pct"]},
                channels=rule.channels,
            )
            created += int(res.created)
    return created


def _low_stock_alerts(farm, recipients, today) -> int:
    rule = effective_rule(farm, NotificationRule.RULE_LOW_STOCK)
    if not rule.enabled:
        return 0
    created = 0
    items = InventoryItem.objects.filter(farm=farm, deleted_at__isnull=True)
    for item in items:
        on_hand = _stock_qty(item)
        if on_hand >= float(item.reorder_level):
            continue
        dedupe = f"low_stock:{item.id}:{today.isoformat()}"
        for user in recipients:
            res = notify(
                user=user,
                type=Notification.TYPE_LOW_STOCK,
                title=f"Low stock: {item.name}",
                body=f"{on_hand:g} {item.unit} left (reorder at {float(item.reorder_level):g}).",
                dedupe_key=dedupe,
                tenant_id=farm.id,
                data={"item_id": str(item.id), "on_hand": on_hand},
                channels=rule.channels,
            )
            created += int(res.created)
    return created


def _overdue_alerts(farm, recipients, today) -> int:
    rule = effective_rule(farm, NotificationRule.RULE_OVERDUE)
    if not rule.enabled:
        return 0
    grace = int(rule.params.get("grace_days", 0))
    cutoff = today - timedelta(days=grace)
    created = 0
    for task in planned_tasks_for_farm(farm, window_to=today):
        if task["status"] != "overdue":
            continue
        if date.fromisoformat(task["target_date"]) > cutoff:
            continue
        dedupe = f"overdue:{task['enterprise_id']}:{task['activity_type']}:{task['target_date']}"
        for user in recipients:
            res = notify(
                user=user,
                type=Notification.TYPE_OVERDUE,
                title=f"Overdue: {task['label']}",
                body=f"{task['enterprise_name']} — was due {task['target_date']}.",
                dedupe_key=dedupe,
                tenant_id=farm.id,
                data={"enterprise_id": task["enterprise_id"]},
                channels=rule.channels,
            )
            created += int(res.created)
    return created


def run_daily_digest(*, now=None) -> int:
    """Send each opted-in user their summary at their chosen local hour."""
    now = now or timezone.localtime()
    today = now.date()
    hour = now.hour
    created = 0
    prefs = DigestPreference.objects.filter(enabled=True, send_hour=hour).select_related("user")
    for pref in prefs:
        if pref.last_sent_on == today:
            continue
        user = pref.user
        unread = Notification.objects.filter(user=user, is_read=False).count()
        body = f"You have {unread} unread alert(s)." if unread else "All caught up — no open alerts."
        res = notify(
            user=user,
            type=Notification.TYPE_DIGEST,
            title="Your daily farm summary",
            body=body,
            dedupe_key=f"digest:{user.id}:{today.isoformat()}",
            data={"unread": unread},
            channels=(CHANNEL_IN_APP,),
        )
        pref.last_sent_on = today
        pref.save(update_fields=["last_sent_on"])
        created += int(res.created)
    return created
