"""Tool definitions + executors for the co-pilot.

`farm_tool_specs()` returns Anthropic-format tool schemas. `make_executor(farm, user)`
returns a callable that runs a named tool against that farm's real data and
returns a human-readable string (money pre-formatted in naira). The same
executor backs both providers — the stub calls it directly by keyword, the
Claude provider calls it from the tool-use loop.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.enterprises.calendar import planned_tasks_for_farm
from apps.enterprises.metrics import metrics_for
from apps.enterprises.models import Enterprise
from apps.finance.models import Account, Transaction
from apps.finance.serializers import _balance_kobo
from apps.inventory.models import InventoryItem
from apps.inventory.serializers import _stock_qty
from apps.notifications.dispatch import notify
from apps.notifications.models import Notification


def _naira(kobo: int) -> str:
    return f"₦{kobo / 100:,.0f}"


def farm_tool_specs() -> list[dict]:
    return [
        {
            "name": "get_financial_summary",
            "description": "Cash position across all accounts plus income, expense and net "
                           "profit for the farm. Use for any money question.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_enterprise_metrics",
            "description": "Performance metrics (yield, FCR, mortality, ADG, survival, margin) "
                           "for one enterprise by name, or all enterprises if no name given.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "enterprise_name": {"type": "string", "description": "Partial name to match."},
                },
            },
        },
        {
            "name": "get_upcoming_tasks",
            "description": "Calendar tasks (planting, vaccination, deworming, harvest) due soon "
                           "or overdue across the farm's live enterprises.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Look-ahead window in days (default 14)."},
                },
            },
        },
        {
            "name": "get_low_stock",
            "description": "Inventory items at or below their reorder level.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_enterprises",
            "description": "All enterprises on the farm with type and lifecycle state.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "create_reminder",
            "description": "Create an in-app reminder for the user, optionally in N days.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "days_from_now": {"type": "integer"},
                },
                "required": ["title"],
            },
        },
    ]


def make_executor(farm, user):
    def execute(name: str, payload: dict) -> str:
        payload = payload or {}
        if name == "get_financial_summary":
            return _financial_summary(farm)
        if name == "get_enterprise_metrics":
            return _enterprise_metrics(farm, payload.get("enterprise_name"))
        if name == "get_upcoming_tasks":
            return _upcoming_tasks(farm, int(payload.get("days") or 14))
        if name == "get_low_stock":
            return _low_stock(farm)
        if name == "list_enterprises":
            return _list_enterprises(farm)
        if name == "create_reminder":
            return _create_reminder(farm, user, payload)
        return f"Unknown tool: {name}"

    return execute


# ---------- executors ----------

def _financial_summary(farm) -> str:
    accounts = Account.objects.filter(tenant_id=farm.id, deleted_at__isnull=True)
    total = sum(_balance_kobo(a) for a in accounts)
    txns = Transaction.objects.filter(tenant_id=farm.id, deleted_at__isnull=True)
    income = txns.filter(kind="income", amount_kobo__gt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0
    expense = -(txns.filter(kind="expense", amount_kobo__lt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0)
    net = income - expense
    return (
        f"Cash position: {_naira(total)} across {accounts.count()} account(s).\n"
        f"Income to date: {_naira(income)}\n"
        f"Expenses to date: {_naira(expense)}\n"
        f"Net: {_naira(net)}"
    )


def _enterprise_metrics(farm, name: str | None) -> str:
    qs = Enterprise.objects.filter(farm=farm, deleted_at__isnull=True)
    if name:
        qs = qs.filter(name__icontains=name)
    rows = list(qs[:10])
    if not rows:
        return "No matching enterprises found."
    lines = []
    for ent in rows:
        m = metrics_for(ent)
        bits = [f"{ent.name} ({ent.type})"]
        if "yield_kg_per_ha" in m:
            bits.append(f"yield {m['yield_kg_per_ha']} kg/ha")
        if "fcr" in m and m.get("fcr"):
            bits.append(f"FCR {m['fcr']}")
        if "mortality_pct" in m:
            bits.append(f"mortality {m['mortality_pct']}%")
        if "survival_pct" in m:
            bits.append(f"survival {m['survival_pct']}%")
        if "avg_daily_gain_kg" in m and m.get("avg_daily_gain_kg") is not None:
            bits.append(f"ADG {m['avg_daily_gain_kg']} kg/d")
        if "yield_ratio" in m:
            bits.append(f"yield ratio {m['yield_ratio']}")
        if "gross_margin_kobo" in m:
            bits.append(f"margin {_naira(m['gross_margin_kobo'])} ({m.get('margin_status', '')})")
        lines.append(" · ".join(bits))
    return "\n".join(lines)


def _upcoming_tasks(farm, days: int) -> str:
    today = timezone.localdate()
    tasks = planned_tasks_for_farm(farm, window_from=today - timedelta(days=14),
                                   window_to=today + timedelta(days=days))
    pending = [t for t in tasks if t["status"] in ("pending", "overdue")][:12]
    if not pending:
        return "No upcoming or overdue tasks."
    return "\n".join(
        f"[{t['status'].upper()}] {t['label']} — {t['enterprise_name']} (due {t['target_date']})"
        for t in pending
    )


def _low_stock(farm) -> str:
    items = InventoryItem.objects.filter(farm=farm, deleted_at__isnull=True)
    low = [i for i in items if _stock_qty(i) < float(i.reorder_level)]
    if not low:
        return "No items are below their reorder level."
    return "\n".join(
        f"{i.name}: {_stock_qty(i):g} {i.unit} left (reorder at {float(i.reorder_level):g})"
        for i in low
    )


def _list_enterprises(farm) -> str:
    rows = Enterprise.objects.filter(farm=farm, deleted_at__isnull=True)
    if not rows:
        return "No enterprises yet."
    return "\n".join(f"{e.name} — {e.type}, {e.lifecycle_state}" for e in rows)


def _create_reminder(farm, user, payload: dict) -> str:
    title = payload.get("title") or "Reminder"
    body = payload.get("body") or ""
    days = int(payload.get("days_from_now") or 0)
    when = (timezone.localdate() + timedelta(days=days)).isoformat()
    res = notify(
        user=user,
        type=Notification.TYPE_CALENDAR,
        title=title,
        body=body or f"Reminder for {when}",
        dedupe_key=f"copilot:{user.id}:{title}:{when}",
        tenant_id=farm.id,
        data={"source": "copilot", "due": when},
    )
    return f"Reminder created: \"{title}\" for {when}." if res.created else "That reminder already exists."
