"""Seed a maize crop_cycle enterprise + activities so the Plan tab has data.

Usage:
  python manage.py seed_maize_demo --email onahjonah@gmail.com
  python manage.py seed_maize_demo --farm-id <uuid>
  python manage.py seed_maize_demo --email <…> --reset

The seed places the planting date 55 days before today and records activities
on each template anchor up through second weeding (-20d). It deliberately
skips the urea top-dressing (-13d, overdue) and leaves spraying (+1d) and
harvest (+55d) for the user to see as upcoming. Costs are realistic for 5 ha.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.activities.models import Activity
from apps.enterprises.models import Enterprise, EnterprisePlan
from apps.farms.models import Farm, StaffMembership

User = get_user_model()

DEMO_NAME = "Demo · Maize 5 ha"


class Command(BaseCommand):
    help = "Seed a maize enterprise + activities for the Plan tab demo."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Farm owner email")
        parser.add_argument("--farm-id", help="Specific Farm UUID")
        parser.add_argument(
            "--reset", action="store_true",
            help="Hard-delete the existing demo enterprise + its activities before seeding.",
        )

    def handle(self, *args, **opts):
        farm = self._resolve_farm(opts.get("email"), opts.get("farm_id"))
        actor = self._actor(farm)

        if opts["reset"]:
            existing = Enterprise.objects.filter(farm=farm, name=DEMO_NAME)
            count = existing.count()
            for ent in existing:
                Activity.objects.filter(enterprise=ent).delete()
                ent.delete()
            self.stdout.write(self.style.WARNING(
                f"Removed {count} prior demo enterprise(s) and their activities."
            ))

        if Enterprise.objects.filter(farm=farm, name=DEMO_NAME).exists():
            raise CommandError(
                f"'{DEMO_NAME}' already exists on this farm. Re-run with --reset."
            )

        today = date.today()
        planting_date = today - timedelta(days=55)
        harvest_target = planting_date + timedelta(days=110)

        with transaction.atomic():
            ent = Enterprise.objects.create(
                tenant_id=farm.id,
                farm=farm,
                type=Enterprise.TYPE_CROP,
                name=DEMO_NAME,
                lifecycle_state=Enterprise.LIFECYCLE_ACTIVE,
                start_date=planting_date,
                attrs={
                    "crop": "maize",
                    "variety": "SAMMAZ 52",
                    "area_ha": 5.0,
                    "planting_date": planting_date.isoformat(),
                    "expected_harvest_date": harvest_target.isoformat(),
                },
            )

            # (template_day_offset, activity_type, cost_naira, notes, attrs)
            recorded = [
                (-7,  "land_prep",   75_000,  "Ploughed and harrowed 5 ha",
                    {"area_ha": 5.0, "method": "Plough + harrow"}),
                (0,   "planting",    75_000,  "Planted SAMMAZ 52, 75×25 spacing",
                    {"variety": "SAMMAZ 52", "area_ha": 5.0, "seed_kg": 125.0}),
                (14,  "weeding",     50_000,  "First weeding · manual",
                    {"area_ha": 5.0, "labor": "8 people · 1 day"}),
                (21,  "fertilizing", 700_000, "Basal NPK 20-10-10, 4 bags / ha",
                    {"fertilizer": "NPK 20-10-10", "bags": 20.0}),
                (35,  "weeding",     50_000,  "Second weeding",
                    {"area_ha": 5.0, "labor": "8 people · 1 day"}),
                # intentionally skip 42 (urea top dressing) → will show "overdue"
                # skip 56 (spraying) → "pending tomorrow"
                # skip 110 (harvest) → "pending later"
            ]
            for offset, type_, cost_naira, notes, attrs in recorded:
                occurred_on = planting_date + timedelta(days=offset)
                occurred_at = datetime.combine(occurred_on, time(9, 0), tzinfo=timezone.utc)
                Activity.objects.create(
                    tenant_id=farm.id,
                    enterprise=ent,
                    type=type_,
                    actor_user=actor,
                    performed_by=actor,
                    occurred_at=occurred_at,
                    weather=Activity.WEATHER_CLEAR,
                    cost_kobo=cost_naira * 100,
                    notes=notes,
                    attrs=attrs,
                )

            # Per-enterprise budget plan (powers the Plan tab money summary).
            # 5 ha × ₦330,000/ha = ₦1,650,000 total.
            EnterprisePlan.objects.create(
                tenant_id=farm.id,
                enterprise=ent,
                budget_lines=[
                    {"id": "prep",    "label": "Land preparation",     "icon": "tractor",  "planned_kobo": 180_000_00},
                    {"id": "seed",    "label": "Seeds",                "icon": "seed",     "planned_kobo":  95_000_00},
                    {"id": "fert",    "label": "Fertilizer",           "icon": "seed",     "planned_kobo": 420_000_00},
                    {"id": "herb",    "label": "Herbicide & pesticide","icon": "leaf",     "planned_kobo": 110_000_00},
                    {"id": "labour",  "label": "Labour",               "icon": "team",     "planned_kobo": 380_000_00},
                    {"id": "mech",    "label": "Machinery",            "icon": "tractor",  "planned_kobo": 140_000_00},
                    {"id": "trans",   "label": "Transport",            "icon": "cart",     "planned_kobo":  80_000_00},
                    {"id": "harvest", "label": "Harvest & threshing",  "icon": "tractor",  "planned_kobo": 160_000_00},
                    {"id": "store",   "label": "Storage & packaging",  "icon": "bag",      "planned_kobo":  60_000_00},
                    {"id": "misc",    "label": "Miscellaneous",        "icon": "more",     "planned_kobo":  25_000_00},
                ],
                # 5 ha × 1,600 kg/ha = 8,000 kg expected
                expected_yield_kg=8000,
                expected_unit_price_kobo=480_00,  # ₦480/kg
                price_reference="Iseyin market avg.",
                notes="Wet season 2026 — based on SAMMAZ 52 historical performance.",
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded '{DEMO_NAME}' on farm {farm.name} ({farm.id}).\n"
            f"  · planted {planting_date.isoformat()} ({(today - planting_date).days}d ago)\n"
            f"  · {len(recorded)} activities recorded\n"
            f"  · Plan tab should show:\n"
            f"      Done · land prep, planting, 1st weeding, basal NPK, 2nd weeding\n"
            f"      Overdue · urea top dressing (~13d ago)\n"
            f"      This week · foliar / pest check\n"
            f"      Later · harvest ({harvest_target.isoformat()})"
        ))

    # ---------- helpers ----------

    def _resolve_farm(self, email: str | None, farm_id: str | None) -> Farm:
        if farm_id:
            try:
                return Farm.objects.get(id=farm_id)
            except Farm.DoesNotExist as exc:
                raise CommandError(f"No farm with id={farm_id}") from exc

        if not email:
            raise CommandError("Pass --email <owner email> or --farm-id <uuid>.")

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with email={email}") from exc

        farm = (
            Farm.objects.filter(owner=user).order_by("-created_at").first()
            or Farm.objects.filter(memberships__user=user)
            .order_by("-created_at").first()
        )
        if farm is None:
            raise CommandError(
                f"{email} has no farms yet. Finish onboarding in the app first."
            )
        return farm

    def _actor(self, farm: Farm) -> User:
        if farm.owner_id:
            return farm.owner
        membership = StaffMembership.objects.filter(farm=farm).first()
        if membership:
            return membership.user
        raise CommandError(f"Farm {farm.id} has no owner or staff to attribute activities to.")
