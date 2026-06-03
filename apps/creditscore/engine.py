"""Farm Credit Score / Operational Track Record (PRD M16).

A composite 300–850 score (familiar credit-score range) built from four
explainable components, each scored 0–100 then weighted:

  - record_completeness (30%) — does the farm keep a full operational record?
    enterprises with lifecycle, activities logged, inventory + accounts set up.
  - activity_consistency (25%) — are activities logged regularly, not in bursts?
    measured over recent weeks of activity.
  - financial_performance (25%) — positive margins, real transaction volume.
  - repayment_history (20%) — on-platform loan repayments, if any (M18). Neutral
    (not penalised) when there's no loan history yet.

The score is the farm's to own and share (PRD); partners read it only through an
M14 consent grant. Computation is deterministic and fully explainable — every
component returns the factors that drove it.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.finance.models import Account, Transaction
from apps.inventory.models import InventoryItem

WEIGHTS = {
    "record_completeness": 0.30,
    "activity_consistency": 0.25,
    "financial_performance": 0.25,
    "repayment_history": 0.20,
}
SCORE_MIN = 300
SCORE_MAX = 850

# Activity-consistency window.
CONSISTENCY_WEEKS = 8
TARGET_ACTIVE_WEEKS = 6  # weeks (of the window) with ≥1 activity for full marks


def compute_score(farm) -> dict[str, Any]:
    components = {
        "record_completeness": _record_completeness(farm),
        "activity_consistency": _activity_consistency(farm),
        "financial_performance": _financial_performance(farm),
        "repayment_history": _repayment_history(farm),
    }
    weighted_0_100 = sum(components[k]["score"] * WEIGHTS[k] for k in WEIGHTS)
    score = round(SCORE_MIN + (weighted_0_100 / 100) * (SCORE_MAX - SCORE_MIN))
    return {
        "farm_id": str(farm.id),
        "score": score,
        "band": _band(score),
        "max_score": SCORE_MAX,
        "min_score": SCORE_MIN,
        "components": components,
        "weights": WEIGHTS,
        "computed_at": timezone.now().isoformat(),
    }


def _band(score: int) -> str:
    if score >= 740:
        return "excellent"
    if score >= 670:
        return "good"
    if score >= 580:
        return "fair"
    return "building"


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _record_completeness(farm) -> dict[str, Any]:
    enterprises = Enterprise.objects.filter(farm=farm, deleted_at__isnull=True)
    has_enterprise = enterprises.exists()
    activity_count = Activity.objects.filter(tenant_id=farm.id, deleted_at__isnull=True).count()
    has_inventory = InventoryItem.objects.filter(farm=farm, deleted_at__isnull=True).exists()
    has_accounts = Account.objects.filter(tenant_id=farm.id, deleted_at__isnull=True).exists()

    # Build the 0-100 from weighted presence + activity depth.
    score = 0.0
    score += 30 if has_enterprise else 0
    score += min(activity_count, 40) / 40 * 40  # up to 40 pts at 40+ activities
    score += 15 if has_inventory else 0
    score += 15 if has_accounts else 0
    return {
        "score": round(_clamp(score), 1),
        "factors": {
            "has_enterprise": has_enterprise,
            "activity_count": activity_count,
            "has_inventory": has_inventory,
            "has_accounts": has_accounts,
        },
    }


def _activity_consistency(farm) -> dict[str, Any]:
    now = timezone.now()
    window_start = now - timedelta(weeks=CONSISTENCY_WEEKS)
    acts = Activity.objects.filter(
        tenant_id=farm.id, deleted_at__isnull=True, occurred_at__gte=window_start,
    ).values_list("occurred_at", flat=True)
    weeks_with_activity = {
        int((now - a).days // 7) for a in acts
    }
    active_weeks = len(weeks_with_activity)
    score = min(active_weeks, TARGET_ACTIVE_WEEKS) / TARGET_ACTIVE_WEEKS * 100
    return {
        "score": round(_clamp(score), 1),
        "factors": {
            "window_weeks": CONSISTENCY_WEEKS,
            "active_weeks": active_weeks,
            "target_active_weeks": TARGET_ACTIVE_WEEKS,
        },
    }


def _financial_performance(farm) -> dict[str, Any]:
    txns = Transaction.objects.filter(tenant_id=farm.id, deleted_at__isnull=True)
    txn_count = txns.count()
    from django.db.models import Sum
    income = txns.filter(amount_kobo__gt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0
    expense = -(txns.filter(amount_kobo__lt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0)
    net = income - expense

    # Volume component (up to 50) + profitability component (up to 50).
    volume = min(txn_count, 20) / 20 * 50
    if income + expense == 0:
        profitability = 0.0
    else:
        margin_ratio = net / (income + expense)  # -1..1
        profitability = _clamp((margin_ratio + 1) / 2 * 50)  # map to 0..50
    return {
        "score": round(_clamp(volume + profitability), 1),
        "factors": {
            "transaction_count": txn_count,
            "income_kobo": int(income),
            "expense_kobo": int(expense),
            "net_kobo": int(net),
        },
    }


def _repayment_history(farm) -> dict[str, Any]:
    """On-platform loan repayment record. Neutral (60/100) when no loans yet —
    absence of history shouldn't penalise a farm, but a clean record rewards it.
    M18 loans populate this; until then it's the neutral baseline."""
    try:
        from apps.finance_partners.models import LoanApplication  # M18, optional
    except Exception:  # noqa: BLE001 — M18 not present yet
        return {"score": 60.0, "factors": {"loans_on_platform": 0, "note": "no loan history"}}

    loans = LoanApplication.objects.filter(farm=farm)
    total = loans.count()
    if total == 0:
        return {"score": 60.0, "factors": {"loans_on_platform": 0, "note": "no loan history"}}
    repaid = loans.filter(status="repaid").count()
    defaulted = loans.filter(status="defaulted").count()
    score = _clamp(60 + (repaid * 20) - (defaulted * 40))
    return {
        "score": round(score, 1),
        "factors": {"loans_on_platform": total, "repaid": repaid, "defaulted": defaulted},
    }
