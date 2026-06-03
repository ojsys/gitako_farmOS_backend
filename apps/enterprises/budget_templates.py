"""Auto-generated cost-breakdown (budget) estimates for a season plan.

The sibling of `calendar.py`: where the calendar turns an enterprise into the
*activities* to do, this turns it into the *money to budget* for those
activities. Templates are deliberate, editable starting points — the farmer
tweaks the lines, and `total_budget_kobo` (money to spend) is just their sum.

Scaling:
  - Crops    — figures are per hectare, scaled by `attrs.area_ha`.
  - Flocks   — figures are per 100 birds, scaled by `attrs.bird_count / 100`.
  - Herds    — figures are per 100 head, scaled by `attrs.herd_size / 100`.
  - Ponds    — figures are per 100 fingerlings, scaled by count / 100.

All money is in kobo (₦1 = 100 kobo). Icon strings map to the mobile budget
tile icon set (seed, leaf, team, cart, bag, chicken, syringe, vet, egg, water,
tractor).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetLine:
    id: str
    label: str
    icon: str
    per_unit_kobo: int  # per hectare (crops) or per 100 animals (livestock)


# Optional expected outcome to seed a coherent plan (yield + price). Per the
# same unit basis as the budget (per ha / per 100 animals).
@dataclass
class Outcome:
    yield_per_unit_kg: float
    price_kobo: int  # ₦/kg in kobo


# ---------- Crops (per hectare) ----------

_MAIZE = [
    BudgetLine("land_prep", "Land preparation", "tractor", 4_000_000),
    BudgetLine("seed", "Seed", "seed", 2_500_000),
    BudgetLine("fertilizer", "Fertilizer (NPK + urea)", "leaf", 9_000_000),
    BudgetLine("chemicals", "Agro-chemicals", "water", 2_500_000),
    BudgetLine("labour", "Labour", "team", 6_000_000),
    BudgetLine("harvest_transport", "Harvest & transport", "cart", 2_000_000),
]
_RICE = [
    BudgetLine("land_prep", "Land prep / puddling", "tractor", 5_500_000),
    BudgetLine("seed", "Seed", "seed", 3_000_000),
    BudgetLine("fertilizer", "Fertilizer", "leaf", 9_500_000),
    BudgetLine("chemicals", "Agro-chemicals", "water", 3_000_000),
    BudgetLine("labour", "Labour", "team", 8_000_000),
    BudgetLine("harvest_transport", "Harvest & transport", "cart", 3_000_000),
]
_CASSAVA = [
    BudgetLine("land_prep", "Land prep / ridging", "tractor", 6_000_000),
    BudgetLine("cuttings", "Stem cuttings", "seed", 2_000_000),
    BudgetLine("fertilizer", "Fertilizer", "leaf", 6_000_000),
    BudgetLine("chemicals", "Weed control", "water", 2_000_000),
    BudgetLine("labour", "Labour", "team", 9_000_000),
    BudgetLine("harvest_transport", "Harvest & transport", "cart", 4_000_000),
]
_GENERIC_CROP = [
    BudgetLine("land_prep", "Land preparation", "tractor", 4_500_000),
    BudgetLine("seed", "Seed / planting material", "seed", 2_500_000),
    BudgetLine("fertilizer", "Fertilizer", "leaf", 7_000_000),
    BudgetLine("chemicals", "Crop protection", "water", 2_500_000),
    BudgetLine("labour", "Labour", "team", 6_500_000),
    BudgetLine("harvest_transport", "Harvest & transport", "cart", 2_500_000),
]

CROP_BUDGETS: dict[str, list[BudgetLine]] = {
    "maize": _MAIZE,
    "rice": _RICE,
    "cassava": _CASSAVA,
}
CROP_OUTCOMES: dict[str, Outcome] = {
    "maize": Outcome(2500, 30_000),    # 2.5 t/ha @ ₦300/kg
    "rice": Outcome(3500, 45_000),     # 3.5 t/ha @ ₦450/kg
    "cassava": Outcome(15000, 6_000),  # 15 t/ha @ ₦60/kg
}
GENERIC_CROP_OUTCOME = Outcome(2000, 25_000)  # 2 t/ha @ ₦250/kg

# ---------- Flocks (per 100 birds) ----------

_BROILER = [
    BudgetLine("chicks", "Day-old chicks", "chicken", 12_000_000),
    BudgetLine("feed", "Feed", "bag", 24_000_000),
    BudgetLine("meds", "Vaccines & medication", "syringe", 1_800_000),
    BudgetLine("brooding", "Brooding & litter", "leaf", 1_400_000),
    BudgetLine("labour", "Labour", "team", 1_800_000),
    BudgetLine("misc", "Miscellaneous", "cart", 1_000_000),
]
_GENERIC_FLOCK = [
    BudgetLine("chicks", "Day-old birds", "chicken", 10_000_000),
    BudgetLine("feed", "Feed", "bag", 18_000_000),
    BudgetLine("meds", "Vaccines & medication", "syringe", 1_600_000),
    BudgetLine("housing", "Housing & litter", "leaf", 1_400_000),
    BudgetLine("labour", "Labour", "team", 1_600_000),
    BudgetLine("misc", "Miscellaneous", "cart", 1_000_000),
]
FLOCK_BUDGETS: dict[str, list[BudgetLine]] = {
    "broiler": _BROILER,
}
FLOCK_OUTCOMES: dict[str, Outcome] = {
    # 100 birds → ~230 kg live @ ₦1,800/kg.
    "broiler": Outcome(230, 180_000),
}
GENERIC_FLOCK_OUTCOME = Outcome(180, 150_000)

# ---------- Herds (per 100 head) ----------

_GENERIC_HERD = [
    BudgetLine("feed", "Feed & fodder", "bag", 60_000_000),
    BudgetLine("health", "Health & veterinary", "vet", 12_000_000),
    BudgetLine("labour", "Labour", "team", 15_000_000),
    BudgetLine("minerals", "Minerals & supplements", "leaf", 6_000_000),
    BudgetLine("misc", "Miscellaneous", "cart", 5_000_000),
]

# ---------- Ponds (per 100 fingerlings) ----------

_GENERIC_POND = [
    BudgetLine("fingerlings", "Fingerlings", "egg", 5_000_000),
    BudgetLine("feed", "Feed", "bag", 25_000_000),
    BudgetLine("water", "Water & treatment", "water", 2_000_000),
    BudgetLine("labour", "Labour", "team", 2_500_000),
    BudgetLine("misc", "Miscellaneous", "cart", 1_200_000),
]


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _round_naira_100(kobo: float) -> int:
    """Round to the nearest ₦100 so estimates read cleanly."""
    return int(round(kobo / 10_000) * 10_000)


def _template_and_scale(enterprise) -> tuple[list[BudgetLine], float]:
    attrs = enterprise.attrs or {}
    t = enterprise.type
    if t == "crop_cycle":
        crop = str(attrs.get("crop", "")).lower()
        scale = _num(attrs.get("area_ha"), 0.0) or 1.0
        return CROP_BUDGETS.get(crop, _GENERIC_CROP), scale
    if t == "flock":
        kind = str(attrs.get("kind", "")).lower()
        birds = _num(attrs.get("bird_count"), 0.0) or 100.0
        return FLOCK_BUDGETS.get(kind, _GENERIC_FLOCK), birds / 100.0
    if t == "herd":
        head = _num(attrs.get("herd_size"), 0.0) or 100.0
        return _GENERIC_HERD, head / 100.0
    if t == "pond":
        count = _num(attrs.get("fingerling_count"), 0.0) or 100.0
        return _GENERIC_POND, count / 100.0
    return [], 0.0


def budget_lines_for(enterprise) -> list[dict]:
    """Scaled cost-breakdown lines for an enterprise (empty for unknown types)."""
    template, scale = _template_and_scale(enterprise)
    if not template or scale <= 0:
        return []
    return [
        {
            "id": line.id,
            "label": line.label,
            "icon": line.icon,
            "planned_kobo": _round_naira_100(line.per_unit_kobo * scale),
        }
        for line in template
    ]


def expected_outcome_for(enterprise) -> tuple[float | None, int | None]:
    """Default (expected_yield_kg, expected_unit_price_kobo) — None where we
    don't ship a confident estimate (herd/pond/processing)."""
    attrs = enterprise.attrs or {}
    t = enterprise.type
    if t == "crop_cycle":
        crop = str(attrs.get("crop", "")).lower()
        out = CROP_OUTCOMES.get(crop, GENERIC_CROP_OUTCOME)
        area = _num(attrs.get("area_ha"), 0.0) or 1.0
        return round(out.yield_per_unit_kg * area, 2), out.price_kobo
    if t == "flock":
        kind = str(attrs.get("kind", "")).lower()
        out = FLOCK_OUTCOMES.get(kind, GENERIC_FLOCK_OUTCOME)
        birds = _num(attrs.get("bird_count"), 0.0) or 100.0
        return round(out.yield_per_unit_kg * birds / 100.0, 2), out.price_kobo
    return None, None


def ensure_plan_budget(plan, enterprise) -> bool:
    """Idempotently seed a plan with auto-generated cost lines + expected
    outcome. Only fills what's empty, never overwrites the farmer's edits, and
    never touches a locked plan. Returns True if anything was written."""
    if plan.locked_at is not None:
        return False
    changed = False
    if not plan.budget_lines:
        lines = budget_lines_for(enterprise)
        if lines:
            plan.budget_lines = lines
            changed = True
    if plan.expected_yield_kg is None and plan.expected_unit_price_kobo is None:
        y, price = expected_outcome_for(enterprise)
        if y is not None:
            plan.expected_yield_kg = y
            plan.expected_unit_price_kobo = price
            changed = True
    if changed:
        plan.save(update_fields=["budget_lines", "expected_yield_kg",
                                 "expected_unit_price_kobo", "updated_at"])
    return changed
