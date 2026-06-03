"""Crop-calendar + vaccination-schedule templates.

Given an enterprise + today's date, produce the list of activities that the
user is expected to do over a forward window. Match each planned task to
recorded Activity rows to compute status (done / pending / overdue).

Templates are intentionally simple v1 — they cover the maize + broiler
acceptance cases in the PRD. Per-crop / per-breed nuance lives in
`CROP_TEMPLATES` and `VACCINATION_TEMPLATES` so it's easy to refine without
restructuring the calendar engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from apps.activities.models import Activity


# ---------- Templates ----------

@dataclass
class TemplateEntry:
    day_offset: int   # days after the anchor (planting_date for crops, stocking_date for flocks)
    activity_type: str
    label: str
    notes: str = ""


CROP_TEMPLATES: dict[str, list[TemplateEntry]] = {
    # Maize (rain-fed, generic 110-day cycle)
    "maize": [
        TemplateEntry(-7, "land_prep", "Land prep before planting"),
        TemplateEntry(0, "planting", "Plant maize seed"),
        TemplateEntry(14, "weeding", "First weeding"),
        TemplateEntry(21, "fertilizing", "Basal NPK 20-10-10"),
        TemplateEntry(35, "weeding", "Second weeding"),
        TemplateEntry(42, "fertilizing", "Top dressing — urea"),
        TemplateEntry(56, "spraying", "Foliar / pest check"),
        TemplateEntry(110, "harvesting", "Harvest"),
    ],
    # Cassava (10-month cycle, simplified)
    "cassava": [
        TemplateEntry(-7, "land_prep", "Ridges"),
        TemplateEntry(0, "planting", "Plant stem cuttings"),
        TemplateEntry(30, "weeding", "First weeding"),
        TemplateEntry(60, "fertilizing", "NPK"),
        TemplateEntry(90, "weeding", "Second weeding"),
        TemplateEntry(300, "harvesting", "Harvest"),
    ],
    # Rice (paddy, 4-month cycle)
    "rice": [
        TemplateEntry(-7, "land_prep", "Land prep / puddling"),
        TemplateEntry(0, "planting", "Transplant"),
        TemplateEntry(14, "fertilizing", "Basal application"),
        TemplateEntry(28, "weeding", "First weeding"),
        TemplateEntry(45, "fertilizing", "Top dressing"),
        TemplateEntry(110, "harvesting", "Harvest"),
    ],
    # Vegetables (generic 70-day cycle)
    "vegetables": [
        TemplateEntry(0, "planting", "Transplant seedlings"),
        TemplateEntry(7, "weeding", "Weed"),
        TemplateEntry(14, "fertilizing", "NPK"),
        TemplateEntry(21, "spraying", "Pest check"),
        TemplateEntry(70, "harvesting", "Harvest"),
    ],
    # Yam (8-9 month cycle, simplified)
    "yam": [
        TemplateEntry(-14, "land_prep", "Make heaps / ridges"),
        TemplateEntry(0, "planting", "Plant yam setts"),
        TemplateEntry(30, "weeding", "First weeding"),
        TemplateEntry(45, "fertilizing", "NPK + organic manure"),
        TemplateEntry(60, "staking", "Stake the vines"),
        TemplateEntry(90, "weeding", "Second weeding"),
        TemplateEntry(150, "weeding", "Third weeding"),
        TemplateEntry(240, "harvesting", "Harvest"),
    ],
    # Sorghum (rain-fed, ~120-day cycle)
    "sorghum": [
        TemplateEntry(-7, "land_prep", "Land prep / ploughing"),
        TemplateEntry(0, "planting", "Sow sorghum seed"),
        TemplateEntry(14, "weeding", "First weeding / thinning"),
        TemplateEntry(21, "fertilizing", "Basal NPK"),
        TemplateEntry(40, "fertilizing", "Top dressing — urea"),
        TemplateEntry(45, "weeding", "Second weeding"),
        TemplateEntry(60, "spraying", "Bird / pest watch"),
        TemplateEntry(120, "harvesting", "Harvest"),
    ],
    # Millet (short rain-fed cycle, ~90 days)
    "millet": [
        TemplateEntry(-7, "land_prep", "Land prep"),
        TemplateEntry(0, "planting", "Sow millet seed"),
        TemplateEntry(14, "weeding", "First weeding / thinning"),
        TemplateEntry(21, "fertilizing", "Basal NPK"),
        TemplateEntry(42, "fertilizing", "Top dressing"),
        TemplateEntry(90, "harvesting", "Harvest"),
    ],
    # Groundnut (~110-day cycle)
    "groundnut": [
        TemplateEntry(-7, "land_prep", "Land prep / ridging"),
        TemplateEntry(0, "planting", "Plant groundnut seed"),
        TemplateEntry(21, "weeding", "First weeding"),
        TemplateEntry(35, "spraying", "Leaf-spot / pest check"),
        TemplateEntry(45, "weeding", "Second weeding (avoid disturbing pegs)"),
        TemplateEntry(110, "harvesting", "Lift / harvest"),
    ],
    # Cowpea / beans (~75-day cycle, spray-sensitive)
    "cowpea": [
        TemplateEntry(0, "planting", "Sow cowpea seed"),
        TemplateEntry(14, "weeding", "First weeding"),
        TemplateEntry(28, "spraying", "Flower-thrips spray"),
        TemplateEntry(42, "spraying", "Pod-borer spray"),
        TemplateEntry(75, "harvesting", "Harvest dry pods"),
    ],
    # Soybean (~100-day cycle)
    "soybean": [
        TemplateEntry(-7, "land_prep", "Land prep"),
        TemplateEntry(0, "planting", "Inoculate + sow soybean"),
        TemplateEntry(21, "weeding", "First weeding"),
        TemplateEntry(40, "spraying", "Pest check"),
        TemplateEntry(100, "harvesting", "Harvest"),
    ],
    # Tomato (transplanted, ~90 days to first harvest)
    "tomato": [
        TemplateEntry(0, "planting", "Transplant seedlings"),
        TemplateEntry(10, "weeding", "Weed + earth up"),
        TemplateEntry(14, "fertilizing", "NPK"),
        TemplateEntry(21, "spraying", "Blight / pest spray"),
        TemplateEntry(35, "spraying", "Follow-up spray"),
        TemplateEntry(45, "staking", "Stake plants"),
        TemplateEntry(75, "harvesting", "First harvest"),
    ],
    # Pepper (transplanted, ~100 days to first harvest)
    "pepper": [
        TemplateEntry(0, "planting", "Transplant seedlings"),
        TemplateEntry(10, "weeding", "Weed"),
        TemplateEntry(14, "fertilizing", "NPK"),
        TemplateEntry(21, "spraying", "Pest / disease spray"),
        TemplateEntry(85, "harvesting", "First harvest"),
    ],
}

# Fallback for any crop without a specific template — a sensible generic
# field-crop cycle so the farmer always gets a starting schedule to edit.
GENERIC_CROP_TEMPLATE: list[TemplateEntry] = [
    TemplateEntry(-7, "land_prep", "Land preparation"),
    TemplateEntry(0, "planting", "Planting"),
    TemplateEntry(21, "weeding", "First weeding"),
    TemplateEntry(30, "fertilizing", "Fertilizer application"),
    TemplateEntry(45, "weeding", "Second weeding"),
    TemplateEntry(60, "spraying", "Pest / disease check"),
    TemplateEntry(110, "harvesting", "Harvest"),
]


# Vaccination schedules per breed. Day offsets are from stocking_date (D0 = day-old).
VACCINATION_TEMPLATES: dict[str, list[TemplateEntry]] = {
    "broiler": [
        TemplateEntry(0, "vaccinate", "Marek's (at hatchery — confirm)"),
        TemplateEntry(7, "vaccinate", "Newcastle (LaSota) + IB"),
        TemplateEntry(14, "vaccinate", "Gumboro"),
        TemplateEntry(21, "vaccinate", "Newcastle booster"),
        TemplateEntry(28, "vaccinate", "Gumboro booster"),
    ],
    "layer": [
        TemplateEntry(0, "vaccinate", "Marek's (at hatchery)"),
        TemplateEntry(7, "vaccinate", "Newcastle (LaSota) + IB"),
        TemplateEntry(14, "vaccinate", "Gumboro"),
        TemplateEntry(28, "vaccinate", "Fowl pox"),
        TemplateEntry(56, "vaccinate", "Newcastle booster"),
        TemplateEntry(112, "vaccinate", "Pre-lay (Newcastle + EDS)"),
    ],
    "breeder": [
        TemplateEntry(0, "vaccinate", "Marek's (at hatchery)"),
        TemplateEntry(7, "vaccinate", "Newcastle + IB"),
        TemplateEntry(14, "vaccinate", "Gumboro"),
        TemplateEntry(28, "vaccinate", "Fowl pox"),
        TemplateEntry(120, "vaccinate", "Pre-lay (Newcastle + EDS + IB)"),
    ],
}

# Fallback for poultry/flocks without a specific breed template.
GENERIC_FLOCK_TEMPLATE: list[TemplateEntry] = [
    TemplateEntry(0, "stocking", "Stocking / arrival"),
    TemplateEntry(7, "vaccinate", "First vaccination"),
    TemplateEntry(14, "medicate", "Prophylaxis / vitamins"),
    TemplateEntry(21, "vaccinate", "Second vaccination / booster"),
    TemplateEntry(56, "harvesting", "Target harvest window"),
]


# Livestock health schedules per species. Day offsets are from acquisition_date.
# Generic best-practice prophylaxis for Nigerian smallholder / commercial herds;
# refine per vet guidance without touching the engine.
HERD_HEALTH_TEMPLATES: dict[str, list[TemplateEntry]] = {
    "cattle": [
        TemplateEntry(0, "deworm", "Deworming on arrival"),
        TemplateEntry(7, "vaccinate", "FMD (foot-and-mouth disease)"),
        TemplateEntry(14, "vaccinate", "Anthrax"),
        TemplateEntry(21, "vaccinate", "Blackleg (clostridial)"),
        TemplateEntry(180, "deworm", "Deworming (6-month)"),
    ],
    "goat": [
        TemplateEntry(0, "deworm", "Deworming on arrival"),
        TemplateEntry(7, "vaccinate", "PPR (peste des petits ruminants)"),
        TemplateEntry(21, "vaccinate", "CDT (enterotoxaemia + tetanus)"),
        TemplateEntry(120, "deworm", "Deworming (4-month)"),
    ],
    "sheep": [
        TemplateEntry(0, "deworm", "Deworming on arrival"),
        TemplateEntry(7, "vaccinate", "PPR (peste des petits ruminants)"),
        TemplateEntry(21, "vaccinate", "CDT (enterotoxaemia + tetanus)"),
        TemplateEntry(120, "deworm", "Deworming (4-month)"),
    ],
    "pig": [
        TemplateEntry(0, "deworm", "Deworming on arrival"),
        TemplateEntry(3, "medicate", "Iron supplementation (piglets)"),
        TemplateEntry(14, "vaccinate", "Classical swine fever"),
        TemplateEntry(120, "deworm", "Deworming (4-month)"),
    ],
}

# Fallback for livestock herds without a specific species template.
GENERIC_HERD_TEMPLATE: list[TemplateEntry] = [
    TemplateEntry(0, "acquisition", "Acquisition / arrival"),
    TemplateEntry(7, "deworm", "Initial deworming"),
    TemplateEntry(14, "vaccinate", "Initial vaccination"),
    TemplateEntry(180, "deworm", "Bi-annual deworming"),
    TemplateEntry(365, "vaccinate", "Annual booster"),
]


# Fish-pond care schedule (M10). Not species-specific in v1; offsets from the
# stocking_date. Water-quality checks are manual/optional per the PRD, surfaced
# here as gentle reminders.
POND_CARE_SCHEDULE: list[TemplateEntry] = [
    TemplateEntry(0, "water_change", "Condition water before stocking"),
    TemplateEntry(14, "sample", "First sampling — weigh + sort"),
    TemplateEntry(30, "sample", "Monthly sampling"),
    TemplateEntry(60, "sample", "Sampling + grading"),
    TemplateEntry(90, "sample", "Sampling"),
    TemplateEntry(150, "harvest", "Target harvest window (table size)"),
]

# Generic management tasks (hygiene + inventory) that apply to all livestock
# (flocks + herds) to round out the schedule.
LIVESTOCK_MANAGEMENT_TEMPLATE: list[TemplateEntry] = [
    TemplateEntry(-2, "hygiene", "Prepare and disinfect housing"),
    TemplateEntry(7, "hygiene", "Weekly sanitation check"),
    TemplateEntry(14, "hygiene", "Weekly sanitation check"),
    TemplateEntry(14, "inventory", "Check feed / supply stock"),
    TemplateEntry(21, "hygiene", "Weekly sanitation check"),
    TemplateEntry(28, "hygiene", "Weekly sanitation check"),
    TemplateEntry(28, "inventory", "Check feed / supply stock"),
]


# Gestation periods (days) — used to project parturition dates from a mating
# activity in a later breeding-reminder pass.
GESTATION_DAYS: dict[str, int] = {
    "cattle": 283,
    "goat": 150,
    "sheep": 150,
    "pig": 115,
}


# ---------- Shared template resolution (used by the synth calendar AND the
# persistent SeasonTask materializer, so both stay in lockstep) ----------

def template_for(enterprise) -> tuple[list[TemplateEntry], str]:
    """Return (template entries, source label) for an enterprise, or ([], "")
    if its type/variety has no GAP template."""
    attrs = enterprise.attrs or {}
    if enterprise.type == "crop_cycle":
        # Known crop → its template; anything else → the generic field-crop cycle
        # so every crop enterprise gets an editable starting schedule.
        crop = attrs.get("crop", "").lower()
        return CROP_TEMPLATES.get(crop, GENERIC_CROP_TEMPLATE), "crop_calendar"

    if enterprise.type == "flock":
        kind = attrs.get("kind", "").lower()
        base = VACCINATION_TEMPLATES.get(kind, GENERIC_FLOCK_TEMPLATE)
        return base + LIVESTOCK_MANAGEMENT_TEMPLATE, "flock_management"

    if enterprise.type == "herd":
        species = attrs.get("species", "").lower()
        base = HERD_HEALTH_TEMPLATES.get(species, GENERIC_HERD_TEMPLATE)
        return base + LIVESTOCK_MANAGEMENT_TEMPLATE, "herd_management"

    if enterprise.type == "pond":
        return POND_CARE_SCHEDULE, "pond_schedule"

    return [], ""



# ---------- Engine ----------

def planned_tasks_for_farm(
    farm,
    *,
    window_from: date | None = None,
    window_to: date | None = None,
    enterprise_id=None,
) -> list[dict[str, Any]]:
    """Build the upcoming task list across all live enterprises on `farm`.

    Returns rows sorted by due_date. Status:
      - done     — a matching activity exists within ±5 days of target
      - overdue  — target_date < today and no matching activity
      - pending  — target_date >= today (or within tolerance)

    When `enterprise_id` is set, the result is filtered to that one enterprise
    (used by the per-enterprise Plan screen's Calendar tab).
    """
    today = date.today()
    window_from = window_from or (today - timedelta(days=14))
    window_to = window_to or (today + timedelta(days=90))

    enterprises = farm.enterprises.filter(deleted_at__isnull=True).exclude(
        lifecycle_state__in=["completed", "abandoned"],
    )
    if enterprise_id is not None:
        enterprises = enterprises.filter(id=enterprise_id)

    rows: list[dict[str, Any]] = []
    for ent in enterprises:
        anchor = anchor_date(ent)
        if anchor is None:
            continue
        template, source = template_for(ent)
        if not template:
            continue

        for entry in template:
            target = anchor + timedelta(days=entry.day_offset)
            if target < window_from or target > window_to:
                continue
            status = _match_status(ent, entry, target, today)
            rows.append({
                "enterprise_id": str(ent.id),
                "enterprise_name": ent.name,
                "enterprise_type": ent.type,
                "activity_type": entry.activity_type,
                "label": entry.label,
                "notes": entry.notes,
                "target_date": target.isoformat(),
                "status": status,
                "source": source,
            })

    rows.sort(key=lambda r: r["target_date"])
    return rows


def anchor_date(enterprise) -> date | None:
    """Crops anchor on planting_date; flocks on stocking_date; herds on
    acquisition_date. The day-0 reference for the GAP template."""
    attrs = enterprise.attrs or {}
    if enterprise.type == "crop_cycle":
        key = "planting_date"
    elif enterprise.type == "herd":
        key = "acquisition_date"
    elif enterprise.type == "processing_line":
        key = "started_on"
    else:
        # flock + pond both anchor on stocking_date.
        key = "stocking_date"

    raw = attrs.get(key)
    if not raw:
        # Fall back to enterprise.start_date if attrs don't have it.
        if enterprise.start_date:
            return enterprise.start_date
        # Final fallback: use created_at date so we always have an anchor.
        return enterprise.created_at.date() if hasattr(enterprise, 'created_at') else date.today()

    try:
        from django.utils.dateparse import parse_date, parse_datetime
        parsed = parse_date(str(raw)) or parse_datetime(str(raw))
        if parsed is None:
            return enterprise.start_date or (enterprise.created_at.date() if hasattr(enterprise, 'created_at') else date.today())
        return parsed if isinstance(parsed, date) and not isinstance(parsed, datetime) \
            else parsed.date()
    except Exception:
        return enterprise.start_date or (enterprise.created_at.date() if hasattr(enterprise, 'created_at') else date.today())


def _match_status(enterprise, entry: TemplateEntry, target: date, today: date) -> str:
    tolerance = timedelta(days=5)
    lo = datetime.combine(target - tolerance, datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(target + tolerance, datetime.max.time(), tzinfo=timezone.utc)
    found = Activity.objects.filter(
        enterprise=enterprise,
        type=entry.activity_type,
        occurred_at__gte=lo,
        occurred_at__lte=hi,
        deleted_at__isnull=True,
    ).exists()
    if found:
        return "done"
    if target < today:
        return "overdue"
    return "pending"
