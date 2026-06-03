"""Rules-based anomaly detection for the co-pilot (M12).

Flags unusual expense, mortality spikes, low stock, and overdue (missing
expected) activities. Deliberately rules-based + explainable; the LLM layer can
summarise these, but the detection itself is deterministic and cheap.
"""
from __future__ import annotations

from datetime import timedelta
from statistics import median

from django.utils import timezone

from apps.enterprises.metrics import metrics_for
from apps.enterprises.models import Enterprise
from apps.finance.models import Transaction
from apps.inventory.models import InventoryItem
from apps.inventory.serializers import _stock_qty

MORTALITY_PCT_THRESHOLD = 5.0
EXPENSE_OUTLIER_MULTIPLE = 3.0


def detect_anomalies(farm) -> list[dict]:
    out: list[dict] = []
    out += _mortality_anomalies(farm)
    out += _low_stock_anomalies(farm)
    out += _overdue_anomalies(farm)
    out += _expense_anomalies(farm)
    return out


def _mortality_anomalies(farm) -> list[dict]:
    animals = Enterprise.objects.filter(
        farm=farm,
        type__in=[Enterprise.TYPE_FLOCK, Enterprise.TYPE_HERD, Enterprise.TYPE_POND],
        lifecycle_state="active",
        deleted_at__isnull=True,
    )
    found = []
    for ent in animals:
        m = metrics_for(ent)
        pct = m.get("mortality_pct", 0)
        if pct >= MORTALITY_PCT_THRESHOLD:
            found.append({
                "type": "mortality_spike",
                "severity": "high",
                "enterprise": ent.name,
                "message": f"{ent.name}: mortality at {pct}% (above {MORTALITY_PCT_THRESHOLD}%).",
            })
    return found


def _low_stock_anomalies(farm) -> list[dict]:
    items = InventoryItem.objects.filter(farm=farm, deleted_at__isnull=True)
    return [
        {
            "type": "low_stock",
            "severity": "medium",
            "message": f"{i.name} low: {_stock_qty(i):g} {i.unit} left (reorder at {float(i.reorder_level):g}).",
        }
        for i in items if _stock_qty(i) < float(i.reorder_level)
    ]


def _overdue_anomalies(farm) -> list[dict]:
    from apps.enterprises.calendar import planned_tasks_for_farm

    today = timezone.localdate()
    tasks = planned_tasks_for_farm(farm, window_to=today)
    return [
        {
            "type": "overdue_activity",
            "severity": "medium",
            "enterprise": t["enterprise_name"],
            "message": f"Overdue: {t['label']} for {t['enterprise_name']} (was due {t['target_date']}).",
        }
        for t in tasks if t["status"] == "overdue"
    ][:10]


def _expense_anomalies(farm) -> list[dict]:
    since = timezone.now() - timedelta(days=30)
    expenses = list(
        Transaction.objects.filter(
            tenant_id=farm.id, kind="expense", deleted_at__isnull=True, posted_at__gte=since,
        ).values_list("amount_kobo", flat=True)
    )
    # amounts are negative; work in positive magnitudes
    mags = sorted(-a for a in expenses if a < 0)
    if len(mags) < 4:
        return []
    med = median(mags)
    if med <= 0:
        return []
    biggest = mags[-1]
    if biggest >= med * EXPENSE_OUTLIER_MULTIPLE:
        return [{
            "type": "unusual_expense",
            "severity": "low",
            "message": (
                f"Largest expense in the last 30 days (₦{biggest / 100:,.0f}) is over "
                f"{EXPENSE_OUTLIER_MULTIPLE:g}× the typical ₦{med / 100:,.0f}."
            ),
        }]
    return []
