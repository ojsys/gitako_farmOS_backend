"""Compute per-enterprise metrics on demand.

Pulls from Activity.attrs (where the actual quantities live) + financial
Transactions tagged to the enterprise. We compute on the fly rather than
maintaining a denormalized table — the volume per enterprise is small
(hundreds of activities) and read latency stays well under the API budget.

Crops (yield + margin):
    harvest_kg            = sum(activity.attrs.harvest_kg) for type=harvesting
    area_ha               = enterprise.attrs.area_ha (set at creation)
    yield_kg_per_ha       = harvest_kg / area_ha
    total_cost_kobo       = -sum(transaction.amount_kobo where amount<0)
    gross_revenue_kobo    = sum(transaction.amount_kobo where amount>0)
    gross_margin_kobo     = revenue - cost

Flock (FCR + margin):
    initial_bird_count    = enterprise.attrs.bird_count
    mortality_count       = sum(activity.attrs.count) for type=mortality
    current_count         = initial - mortality
    mortality_pct         = mortality / initial * 100
    total_feed_kg         = sum(activity.attrs.quantity_kg) for type=feed
    weight_samples        = [(occurred_at, avg_weight_g, sample_size)] for type=weigh
    latest_avg_weight_g   = weight_samples[-1].avg_weight_g
    total_weight_g        = current_count * latest_avg_weight_g  (estimate)
    fcr                   = (total_feed_g) / (total_weight_g - initial_weight_g_estimate)
    days_on_feed          = (now - stocking_date).days
    projected_market_weight_g = simple linear extrap from weight samples
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from django.db.models import Sum

from apps.activities.models import Activity

from .broiler_standards import resolve_targets, target_weight_g

# Day-old chick weight estimate (varies a bit by breed; this is a reasonable
# average we can refine when the user enters their own initial weight later).
DAY_OLD_WEIGHT_G = 40

# Fingerling stocking weight estimate (catfish/tilapia); refine when the user
# enters their own stocking weight.
FINGERLING_WEIGHT_G = 5


def metrics_for(enterprise) -> dict[str, Any]:
    if enterprise.type == "crop_cycle":
        return _crop_metrics(enterprise)
    if enterprise.type == "flock":
        return _flock_metrics(enterprise)
    if enterprise.type == "herd":
        return _herd_metrics(enterprise)
    if enterprise.type == "pond":
        return _pond_metrics(enterprise)
    if enterprise.type == "processing_line":
        return _processing_metrics(enterprise)
    return {"enterprise_id": str(enterprise.id), "type": enterprise.type}


# ---------- Crops ----------

def _crop_metrics(enterprise) -> dict[str, Any]:
    attrs = enterprise.attrs or {}
    area_ha = _to_float(attrs.get("area_ha"))

    harvest_kg = 0.0
    for act in enterprise.activities.filter(
        type="harvesting", deleted_at__isnull=True,
    ):
        harvest_kg += _to_float((act.attrs or {}).get("harvest_kg"))

    yield_kg_per_ha = (harvest_kg / area_ha) if area_ha > 0 else 0.0

    cost_kobo, revenue_kobo = _money_in_out(enterprise)

    return {
        "enterprise_id": str(enterprise.id),
        "type": enterprise.type,
        "lifecycle_state": enterprise.lifecycle_state,
        "crop": attrs.get("crop", ""),
        "variety": attrs.get("variety", ""),
        "planting_date": attrs.get("planting_date"),
        "area_ha": area_ha,
        "harvest_kg": round(harvest_kg, 2),
        "yield_kg_per_ha": round(yield_kg_per_ha, 2),
        "total_cost_kobo": cost_kobo,
        "gross_revenue_kobo": revenue_kobo,
        "gross_margin_kobo": revenue_kobo - cost_kobo,
        "margin_status": "actual" if enterprise.lifecycle_state == "completed" else "projected",
    }


# ---------- Flocks ----------

def _flock_metrics(enterprise) -> dict[str, Any]:
    attrs = enterprise.attrs or {}
    initial = int(_to_float(attrs.get("bird_count")))
    stocking_date = _parse_date(attrs.get("stocking_date"))

    acts = (
        enterprise.activities.filter(deleted_at__isnull=True)
        .order_by("occurred_at")
    )

    mortality = sum(
        int(_to_float((a.attrs or {}).get("count")))
        for a in acts if a.type == "mortality"
    )
    current = max(initial - mortality, 0)

    feed_kg = sum(
        _to_float((a.attrs or {}).get("quantity_kg"))
        for a in acts if a.type == "feed"
    )

    weighings = [
        (
            a.occurred_at,
            _to_float((a.attrs or {}).get("avg_weight_g")),
            int(_to_float((a.attrs or {}).get("sample_size"))),
        )
        for a in acts if a.type == "weigh"
    ]
    weighings = [w for w in weighings if w[1] > 0]

    latest_avg_weight_g = weighings[-1][1] if weighings else 0.0

    if stocking_date:
        days_on_feed = (datetime.now(timezone.utc) - stocking_date).days
    else:
        days_on_feed = 0

    # Total live weight estimate today.
    total_weight_g = current * latest_avg_weight_g

    # FCR = total feed consumed / weight gained.
    # Weight gained = total live weight - (current_count * day-old weight).
    weight_gained_g = total_weight_g - (current * DAY_OLD_WEIGHT_G)
    feed_g = feed_kg * 1000
    fcr = (feed_g / weight_gained_g) if weight_gained_g > 0 else 0.0

    # Projected market weight: linear extrap from weighings if we have ≥2
    # samples, else null. Broilers typically market at 56 days (8 weeks).
    projected_market_weight_g = _project_market_weight(weighings, days_on_feed)

    cost_kobo, revenue_kobo = _money_in_out(enterprise)
    mortality_pct = (mortality / initial * 100) if initial > 0 else 0.0

    # ── Breed standards: targets + actual-vs-target weight curve ──
    targets = resolve_targets(attrs)
    breed = attrs.get("breed")
    cycle_length = targets["cycle_length_days"]
    cycle_day = max(days_on_feed, 0)

    # Actual sample weights keyed by day-on-feed.
    samples: dict[int, float] = {}
    if stocking_date:
        for occurred, g, _size in weighings:
            d = (occurred - stocking_date).days
            if d >= 0:
                samples[d] = g  # later samples on the same day win (sorted asc)

    def _nearest_actual(day, window=3):
        best = None
        for d, g in samples.items():
            if abs(d - day) <= window and (best is None or abs(d - day) < abs(best[0] - day)):
                best = (d, g)
        return int(round(best[1])) if best else None

    curve_days = sorted(
        {1, *range(7, cycle_length + 1, 7), cycle_length}
        | ({cycle_day} if 0 < cycle_day <= cycle_length else set())
    )
    weight_series = [
        {"day": d, "target_g": target_weight_g(breed, d), "actual_g": _nearest_actual(d)}
        for d in curve_days
    ]

    # ── Projected economics (needs a sale price on the batch) ──
    price_kobo = _to_float(attrs.get("sale_price_per_kg_kobo"))
    if not price_kobo:
        price_kobo = _to_float(attrs.get("sale_price_per_kg")) * 100

    projected_revenue = projected_profit = plan_delta = None
    insight = None
    if price_kobo and projected_market_weight_g:
        projected_revenue = int(projected_market_weight_g / 1000 * current * price_kobo)
        projected_profit = projected_revenue - cost_kobo
        planned_alive = initial * (1 - targets["target_mortality_pct"] / 100)
        plan_revenue = int(targets["target_market_weight_g"] / 1000 * planned_alive * price_kobo)
        plan_delta = projected_revenue - plan_revenue
        insight = _flock_insight(fcr or None, mortality_pct, targets, plan_delta)
    elif not price_kobo:
        insight = "Set a sale price (₦/kg) on this batch to see projected revenue & profit."
    elif not projected_market_weight_g:
        insight = "Record a couple of weigh samples to project market weight & revenue."

    return {
        "enterprise_id": str(enterprise.id),
        "name": enterprise.name,
        "type": enterprise.type,
        "lifecycle_state": enterprise.lifecycle_state,
        "kind": attrs.get("kind", ""),
        "breed": breed,
        "breed_label": targets["breed_label"],
        "batch_id": attrs.get("batch_id", ""),
        "stocking_date": attrs.get("stocking_date"),
        "placed_date": attrs.get("stocking_date"),
        "initial_bird_count": initial,
        "current_count": current,
        "mortality_count": mortality,
        "mortality_pct": round(mortality_pct, 2),
        "total_feed_kg": round(feed_kg, 2),
        "latest_avg_weight_g": round(latest_avg_weight_g, 1),
        "total_weight_g": round(total_weight_g, 0),
        "fcr": round(fcr, 2),
        "days_on_feed": days_on_feed,
        "cycle_day": cycle_day,
        "cycle_length": cycle_length,
        "projected_market_weight_g": projected_market_weight_g,
        "targets": {
            "fcr": round(targets["target_fcr"], 2),
            "mortality_pct": round(targets["target_mortality_pct"], 1),
            "market_weight_g": targets["target_market_weight_g"],
        },
        "weight_series": weight_series,
        "projected_revenue_kobo": projected_revenue,
        "projected_profit_kobo": projected_profit,
        "plan_delta_kobo": plan_delta,
        "insight": insight,
        "total_cost_kobo": cost_kobo,
        "gross_revenue_kobo": revenue_kobo,
        "gross_margin_kobo": revenue_kobo - cost_kobo,
        "margin_status": "actual" if enterprise.lifecycle_state == "completed" else "projected",
    }


def _flock_insight(fcr, mortality_pct, targets, plan_delta) -> str:
    """Short headline on how the batch is tracking vs plan."""
    money = ""
    if plan_delta is not None and plan_delta != 0:
        verb = "gain" if plan_delta > 0 else "lose"
        money = f" — at this trajectory you'll {verb} ₦{abs(plan_delta) // 100:,} vs plan"
    t_fcr = targets["target_fcr"]
    if fcr and t_fcr and fcr > t_fcr * 1.02:
        over = (fcr - t_fcr) / t_fcr * 100
        return f"FCR running {over:.0f}% above target{money}."
    t_mort = targets["target_mortality_pct"]
    if mortality_pct is not None and mortality_pct > t_mort:
        return f"Mortality {mortality_pct:.1f}% is over the {t_mort:.0f}% target{money}."
    if plan_delta is not None and plan_delta >= 0:
        return f"On track{money or ' to hit plan'}."
    return f"Tracking below plan{money}."


# ---------- Herds (livestock: cattle / small ruminants / pigs) ----------

def _herd_metrics(enterprise) -> dict[str, Any]:
    """Batch-level livestock metrics (M9). Leads with mortality, ADG (average
    daily gain), and breeding tallies — the KPIs that matter for ruminants and
    pigs (FCR is poultry's headline, not theirs). Weights are in kg.

    Herd `weigh` activities carry attrs.avg_weight_kg + sample_size; counts of
    deaths / offspring / sales / weanings live in attrs.count or
    attrs.offspring_count on the respective activity types.
    """
    attrs = enterprise.attrs or {}
    initial = int(_to_float(attrs.get("herd_size")))
    acquisition_date = _parse_date(attrs.get("acquisition_date"))

    acts = (
        enterprise.activities.filter(deleted_at__isnull=True)
        .order_by("occurred_at")
    )

    mortality = sum(
        int(_to_float((a.attrs or {}).get("count")))
        for a in acts if a.type == "mortality"
    )
    births = sum(
        int(_to_float((a.attrs or {}).get("offspring_count")))
        for a in acts if a.type == "parturition"
    )
    sold = sum(
        int(_to_float((a.attrs or {}).get("count")))
        for a in acts if a.type == "sale"
    )
    matings = sum(1 for a in acts if a.type == "mating")
    weanings = sum(
        int(_to_float((a.attrs or {}).get("count")))
        for a in acts if a.type == "weaning"
    )

    current = max(initial + births - mortality - sold, 0)
    mortality_pct = (mortality / initial * 100) if initial > 0 else 0.0

    feed_kg = sum(
        _to_float((a.attrs or {}).get("quantity_kg"))
        for a in acts if a.type == "feed"
    )

    weighings = [
        (
            a.occurred_at,
            _to_float((a.attrs or {}).get("avg_weight_kg")),
            int(_to_float((a.attrs or {}).get("sample_size"))),
        )
        for a in acts if a.type == "weigh"
    ]
    weighings = [w for w in weighings if w[1] > 0]
    latest_avg_weight_kg = weighings[-1][1] if weighings else 0.0
    avg_daily_gain_kg = _avg_daily_gain_kg(weighings)

    if acquisition_date:
        days_on_farm = (datetime.now(timezone.utc) - acquisition_date).days
    else:
        days_on_farm = 0

    cost_kobo, revenue_kobo = _money_in_out(enterprise)

    return {
        "enterprise_id": str(enterprise.id),
        "type": enterprise.type,
        "lifecycle_state": enterprise.lifecycle_state,
        "species": attrs.get("species", ""),
        "breed": attrs.get("breed", ""),
        "acquisition_date": attrs.get("acquisition_date"),
        "initial_herd_size": initial,
        "current_count": current,
        "mortality_count": mortality,
        "mortality_pct": round(mortality_pct, 2),
        "births_count": births,
        "weanings_count": weanings,
        "matings_count": matings,
        "total_feed_kg": round(feed_kg, 2),
        "latest_avg_weight_kg": round(latest_avg_weight_kg, 1),
        "avg_daily_gain_kg": avg_daily_gain_kg,
        "days_on_farm": days_on_farm,
        "total_cost_kobo": cost_kobo,
        "gross_revenue_kobo": revenue_kobo,
        "gross_margin_kobo": revenue_kobo - cost_kobo,
        "margin_status": "actual" if enterprise.lifecycle_state == "completed" else "projected",
    }


def _avg_daily_gain_kg(weighings) -> float | None:
    """Average daily gain in kg/day from first→last weigh sample. None if <2."""
    if len(weighings) < 2:
        return None
    first, last = weighings[0], weighings[-1]
    span_days = max((last[0] - first[0]).days, 1)
    return round((last[1] - first[1]) / span_days, 3)


# ---------- Ponds (aquaculture: catfish / tilapia) ----------

def _pond_metrics(enterprise) -> dict[str, Any]:
    """Fish-pond metrics (M10). Like poultry, FCR is the headline KPI; we also
    surface survival rate. Weights in grams; `sample` activities carry
    attrs.avg_weight_g + sample_size, deaths/harvests carry attrs.count.
    """
    attrs = enterprise.attrs or {}
    initial = int(_to_float(attrs.get("fingerling_count")))
    stocking_date = _parse_date(attrs.get("stocking_date"))

    acts = enterprise.activities.filter(deleted_at__isnull=True).order_by("occurred_at")

    mortality = sum(
        int(_to_float((a.attrs or {}).get("count")))
        for a in acts if a.type == "mortality"
    )
    harvested = sum(
        int(_to_float((a.attrs or {}).get("count")))
        for a in acts if a.type in ("harvest", "sale")
    )
    current = max(initial - mortality - harvested, 0)
    mortality_pct = (mortality / initial * 100) if initial > 0 else 0.0
    survival_pct = (current / initial * 100) if initial > 0 else 0.0

    feed_kg = sum(
        _to_float((a.attrs or {}).get("quantity_kg"))
        for a in acts if a.type == "feed"
    )

    weighings = [
        (
            a.occurred_at,
            _to_float((a.attrs or {}).get("avg_weight_g")),
            int(_to_float((a.attrs or {}).get("sample_size"))),
        )
        for a in acts if a.type in ("sample", "weigh")
    ]
    weighings = [w for w in weighings if w[1] > 0]
    latest_avg_weight_g = weighings[-1][1] if weighings else 0.0

    harvest_kg = sum(
        _to_float((a.attrs or {}).get("harvest_kg"))
        for a in acts if a.type == "harvest"
    )

    if stocking_date:
        days_in_culture = (datetime.now(timezone.utc) - stocking_date).days
    else:
        days_in_culture = 0

    total_weight_g = current * latest_avg_weight_g
    weight_gained_g = total_weight_g - (current * FINGERLING_WEIGHT_G)
    feed_g = feed_kg * 1000
    fcr = (feed_g / weight_gained_g) if weight_gained_g > 0 else 0.0

    cost_kobo, revenue_kobo = _money_in_out(enterprise)

    return {
        "enterprise_id": str(enterprise.id),
        "type": enterprise.type,
        "lifecycle_state": enterprise.lifecycle_state,
        "species": attrs.get("species", ""),
        "pond_type": attrs.get("pond_type", ""),
        "stocking_date": attrs.get("stocking_date"),
        "initial_fingerling_count": initial,
        "current_count": current,
        "mortality_count": mortality,
        "mortality_pct": round(mortality_pct, 2),
        "survival_pct": round(survival_pct, 2),
        "total_feed_kg": round(feed_kg, 2),
        "latest_avg_weight_g": round(latest_avg_weight_g, 1),
        "harvest_kg": round(harvest_kg, 2),
        "fcr": round(fcr, 2),
        "days_in_culture": days_in_culture,
        "total_cost_kobo": cost_kobo,
        "gross_revenue_kobo": revenue_kobo,
        "gross_margin_kobo": revenue_kobo - cost_kobo,
        "margin_status": "actual" if enterprise.lifecycle_state == "completed" else "projected",
    }


# ---------- Processing lines (agro-processing) ----------

def _processing_metrics(enterprise) -> dict[str, Any]:
    """Agro-processing metrics (M11). A `process` activity records a run with
    attrs.input_kg (raw consumed) and attrs.output_kg (finished goods). Yield
    ratio = output / input — the headline efficiency number (e.g. cassava→garri
    ≈ 0.25). Processing cost + margin come from tagged transactions.
    """
    attrs = enterprise.attrs or {}
    runs = [
        a for a in enterprise.activities.filter(deleted_at__isnull=True)
        if a.type == "process"
    ]
    total_input_kg = sum(_to_float((a.attrs or {}).get("input_kg")) for a in runs)
    total_output_kg = sum(_to_float((a.attrs or {}).get("output_kg")) for a in runs)
    yield_ratio = (total_output_kg / total_input_kg) if total_input_kg > 0 else 0.0

    cost_kobo, revenue_kobo = _money_in_out(enterprise)

    return {
        "enterprise_id": str(enterprise.id),
        "type": enterprise.type,
        "lifecycle_state": enterprise.lifecycle_state,
        "process": attrs.get("process", ""),
        "input_item": attrs.get("input_item", ""),
        "output_item": attrs.get("output_item", ""),
        "runs_count": len(runs),
        "total_input_kg": round(total_input_kg, 2),
        "total_output_kg": round(total_output_kg, 2),
        "yield_ratio": round(yield_ratio, 3),
        "total_cost_kobo": cost_kobo,
        "gross_revenue_kobo": revenue_kobo,
        "gross_margin_kobo": revenue_kobo - cost_kobo,
        "margin_status": "actual" if enterprise.lifecycle_state == "completed" else "projected",
    }


# ---------- helpers ----------

def _money_in_out(enterprise) -> tuple[int, int]:
    """Sum of expense vs income transactions tagged to this enterprise."""
    qs = enterprise.transactions.filter(deleted_at__isnull=True)
    out_neg = qs.filter(amount_kobo__lt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0
    in_pos = qs.filter(amount_kobo__gt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0
    return int(-out_neg), int(in_pos)


def _project_market_weight(weighings, days_on_feed: int) -> float | None:
    """Linear extrap to day 56 (broiler market) from the weighings we have."""
    if len(weighings) < 2 or days_on_feed <= 0:
        return None
    # Sort by date; use first vs last as the slope (simple, robust to outliers
    # for now — can swap for least-squares once we have real data).
    first = weighings[0]
    last = weighings[-1]
    span_days = max((last[0] - first[0]).days, 1)
    g_per_day = (last[1] - first[1]) / span_days
    target_day = 56
    days_remaining = max(target_day - days_on_feed, 0)
    return round(last[1] + g_per_day * days_remaining, 0)


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(s) -> datetime | None:
    if not s:
        return None
    try:
        from django.utils.dateparse import parse_datetime, parse_date
        dt = parse_datetime(str(s)) or parse_date(str(s))
        if dt is None:
            return None
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            return dt
        # parse_date returns a date; turn into UTC midnight datetime
        if hasattr(dt, "year") and not hasattr(dt, "hour"):
            return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
        return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
    except Exception:
        return None
