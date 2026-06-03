from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(phone="+2348010000001")


@pytest.fixture
def farm(owner):
    f = Farm.objects.create(name="Musa's Farm", owner=owner)
    StaffMembership.objects.create(user=owner, farm=f, role=StaffMembership.ROLE_OWNER)
    return f


@pytest.fixture
def authed(api_client, owner, farm):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    return api_client


def test_create_crop_enterprise(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {
            "farm": str(farm.id),
            "type": "crop_cycle",
            "name": "Block A · Maize 2026",
            "lifecycle_state": "active",
            "attrs": {"crop": "maize", "variety": "SAMMAZ 52", "area_ha": 5.0,
                      "planting_date": "2026-05-01"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    ent = Enterprise.objects.get(name="Block A · Maize 2026")
    assert ent.type == "crop_cycle"
    assert ent.tenant_id == farm.id
    assert ent.attrs["area_ha"] == 5.0


def test_create_flock_enterprise(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {
            "farm": str(farm.id),
            "type": "flock",
            "name": "Pen 3 · Broilers Batch 17",
            "attrs": {"kind": "broiler", "batch_id": "B17", "bird_count": 1000,
                      "stocking_date": "2026-05-01"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content


def test_crop_requires_crop_and_area(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {"farm": str(farm.id), "type": "crop_cycle", "name": "Block X", "attrs": {}},
        format="json",
    )
    assert resp.status_code == 400
    assert "attrs" in resp.json()


def test_tenant_scoping(api_client, owner, farm):
    other = User.objects.create_user(phone="+2348010000099")
    other_farm = Farm.objects.create(name="Other", owner=other)
    StaffMembership.objects.create(user=other, farm=other_farm, role=StaffMembership.ROLE_OWNER)
    Enterprise.objects.create(
        farm=other_farm, tenant_id=other_farm.id, type="crop_cycle",
        name="Hidden", attrs={"crop": "rice", "area_ha": 1},
    )

    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.get(reverse("enterprises-list"))
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    assert all(r["farm"] != str(other_farm.id) for r in rows)


def test_delete_soft_deletes(authed, farm):
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle", name="Doomed",
        attrs={"crop": "maize", "area_ha": 1},
    )
    resp = authed.delete(reverse("enterprises-detail", kwargs={"pk": str(ent.id)}))
    assert resp.status_code == 204
    assert not Enterprise.objects.filter(pk=ent.id).exists()
    assert Enterprise.all_objects.filter(pk=ent.id, deleted_at__isnull=False).exists()


def test_crop_metrics_compute_yield_and_margin(authed, farm):
    from apps.activities.models import Activity
    from apps.finance.models import Account, Transaction
    from django.utils import timezone
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle",
        name="Block A · Maize",
        attrs={"crop": "maize", "area_ha": 5.0, "planting_date": "2026-04-01"},
        lifecycle_state="completed",
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="harvesting",
        occurred_at=timezone.now(), attrs={"harvest_kg": 9000},
    )
    acc = Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash", type="cash")
    Transaction.objects.create(
        tenant_id=farm.id, farm=farm, account=acc, enterprise=ent,
        kind="income", amount_kobo=1_800_000_00, posted_at=timezone.now(),
    )
    Transaction.objects.create(
        tenant_id=farm.id, farm=farm, account=acc, enterprise=ent,
        kind="expense", amount_kobo=-450_000_00, posted_at=timezone.now(),
    )
    resp = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)}))
    body = resp.json()
    assert body["area_ha"] == 5.0
    assert body["harvest_kg"] == 9000.0
    assert body["yield_kg_per_ha"] == 1800.0
    assert body["gross_revenue_kobo"] == 1_800_000_00
    assert body["total_cost_kobo"] == 450_000_00
    assert body["gross_margin_kobo"] == 1_350_000_00
    assert body["margin_status"] == "actual"


def test_planned_tasks_endpoint_for_crop(authed, farm):
    from datetime import date, timedelta
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle",
        name="Block A · Maize", lifecycle_state="active",
        attrs={"crop": "maize", "area_ha": 5.0,
               "planting_date": (date.today() - timedelta(days=10)).isoformat()},
    )
    resp = authed.get(reverse("planned-tasks"))
    body = resp.json()
    types = {t["activity_type"] for t in body["tasks"]}
    assert "planting" in types
    assert "weeding" in types
    assert "fertilizing" in types
    planting = [t for t in body["tasks"] if t["activity_type"] == "planting"][0]
    assert planting["status"] in {"overdue", "done"}


def test_planned_tasks_for_flock(authed, farm):
    from datetime import date, timedelta
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="flock",
        name="Pen 3 · Broilers", lifecycle_state="active",
        attrs={"kind": "broiler", "bird_count": 1000,
               "stocking_date": (date.today() - timedelta(days=2)).isoformat()},
    )
    resp = authed.get(reverse("planned-tasks"))
    sources = {t["source"] for t in resp.json()["tasks"]}
    assert "vaccination_schedule" in sources


def test_planned_task_marked_done_when_activity_exists(authed, farm):
    from datetime import date, timedelta
    from apps.activities.models import Activity
    from django.utils import timezone
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle",
        name="Block A · Maize", lifecycle_state="active",
        attrs={"crop": "maize", "area_ha": 5.0,
               "planting_date": (date.today() - timedelta(days=10)).isoformat()},
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="planting",
        occurred_at=timezone.now() - timedelta(days=10),
    )
    resp = authed.get(reverse("planned-tasks"))
    planting = [t for t in resp.json()["tasks"] if t["activity_type"] == "planting"][0]
    assert planting["status"] == "done"


def test_flock_metrics_compute_fcr_and_mortality(authed, farm):
    from datetime import timedelta
    from apps.activities.models import Activity
    from django.utils import timezone
    stocking = (timezone.now() - timedelta(days=21)).date().isoformat()
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="flock",
        name="Pen 3 · Broilers Batch 17",
        attrs={"kind": "broiler", "bird_count": 1000, "stocking_date": stocking},
        lifecycle_state="active",
    )
    # 35 birds died total.
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="mortality",
        occurred_at=timezone.now(), attrs={"count": 20},
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="mortality",
        occurred_at=timezone.now(), attrs={"count": 15},
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="feed",
        occurred_at=timezone.now(), attrs={"quantity_kg": 350},
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
        occurred_at=timezone.now(), attrs={"sample_size": 20, "avg_weight_g": 850},
    )
    resp = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)}))
    body = resp.json()
    assert body["initial_bird_count"] == 1000
    assert body["mortality_count"] == 35
    assert body["current_count"] == 965
    assert body["mortality_pct"] == 3.5
    assert body["total_feed_kg"] == 350.0
    assert body["latest_avg_weight_g"] == 850.0
    # FCR ≈ feed_g / (current × (avg_weight - day-old))
    # = 350,000 / (965 × 810) = 0.448 — accept anything close.
    assert 0.4 <= body["fcr"] <= 0.5
    assert body["days_on_feed"] >= 20


# ---------- Herd (livestock) — M9 ----------

def test_create_herd_enterprise(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {
            "farm": str(farm.id),
            "type": "herd",
            "name": "Sayedero · White Fulani",
            "lifecycle_state": "active",
            "attrs": {"species": "cattle", "breed": "White Fulani", "herd_size": 40,
                      "acquisition_date": "2026-01-15"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    ent = Enterprise.objects.get(name="Sayedero · White Fulani")
    assert ent.type == "herd"
    assert ent.attrs["species"] == "cattle"


def test_herd_requires_species_and_size(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {"farm": str(farm.id), "type": "herd", "name": "Nameless", "attrs": {}},
        format="json",
    )
    assert resp.status_code == 400
    assert "attrs" in resp.json()


def test_herd_rejects_unknown_species(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {"farm": str(farm.id), "type": "herd", "name": "Camels?",
         "attrs": {"species": "camel", "herd_size": 5}},
        format="json",
    )
    assert resp.status_code == 400


def test_herd_metrics_compute_mortality_adg_and_breeding(authed, farm):
    from datetime import timedelta
    from apps.activities.models import Activity
    from django.utils import timezone
    acquisition = (timezone.now() - timedelta(days=60)).date().isoformat()
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="herd",
        name="Goat herd · Kano Brown",
        attrs={"species": "goat", "breed": "Kano Brown", "herd_size": 50,
               "acquisition_date": acquisition},
        lifecycle_state="active",
    )
    # 4 died, 6 born, 2 sold → current = 50 + 6 - 4 - 2 = 50.
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="mortality",
                            occurred_at=timezone.now(), attrs={"count": 4})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="parturition",
                            occurred_at=timezone.now(), attrs={"offspring_count": 6})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="sale",
                            occurred_at=timezone.now(), attrs={"count": 2})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="mating",
                            occurred_at=timezone.now(), attrs={})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="feed",
                            occurred_at=timezone.now(), attrs={"quantity_kg": 120})
    # Two weigh samples 30 days apart: 18kg → 24kg ⇒ ADG = 0.2 kg/day.
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
                            occurred_at=timezone.now() - timedelta(days=30),
                            attrs={"sample_size": 10, "avg_weight_kg": 18})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
                            occurred_at=timezone.now(),
                            attrs={"sample_size": 10, "avg_weight_kg": 24})

    resp = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)}))
    body = resp.json()
    assert body["species"] == "goat"
    assert body["initial_herd_size"] == 50
    assert body["mortality_count"] == 4
    assert body["mortality_pct"] == 8.0
    assert body["births_count"] == 6
    assert body["matings_count"] == 1
    assert body["current_count"] == 50
    assert body["total_feed_kg"] == 120.0
    assert body["latest_avg_weight_kg"] == 24.0
    assert body["avg_daily_gain_kg"] == 0.2
    assert body["days_on_farm"] >= 55


def test_planned_tasks_for_herd(authed, farm):
    from datetime import date, timedelta
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="herd",
        name="Cattle · White Fulani", lifecycle_state="active",
        attrs={"species": "cattle", "herd_size": 30,
               "acquisition_date": (date.today() - timedelta(days=2)).isoformat()},
    )
    resp = authed.get(reverse("planned-tasks"))
    tasks = resp.json()["tasks"]
    sources = {t["source"] for t in tasks}
    types = {t["activity_type"] for t in tasks}
    assert "health_schedule" in sources
    assert "vaccinate" in types or "deworm" in types


# ---------- Pond (aquaculture) — M10 ----------

def test_create_pond_enterprise(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {
            "farm": str(farm.id),
            "type": "pond",
            "name": "Earthen pond 2 · Catfish",
            "lifecycle_state": "active",
            "attrs": {"species": "catfish", "pond_type": "earthen",
                      "fingerling_count": 2000, "stocking_date": "2026-02-01"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert Enterprise.objects.get(name="Earthen pond 2 · Catfish").type == "pond"


def test_pond_requires_species_and_count(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {"farm": str(farm.id), "type": "pond", "name": "Empty", "attrs": {}},
        format="json",
    )
    assert resp.status_code == 400
    assert "attrs" in resp.json()


def test_pond_metrics_compute_fcr_and_survival(authed, farm):
    from datetime import timedelta
    from apps.activities.models import Activity
    from django.utils import timezone
    stocking = (timezone.now() - timedelta(days=90)).date().isoformat()
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="pond",
        name="Earthen pond 2 · Catfish",
        attrs={"species": "catfish", "fingerling_count": 2000, "stocking_date": stocking},
        lifecycle_state="active",
    )
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="mortality",
                            occurred_at=timezone.now(), attrs={"count": 200})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="feed",
                            occurred_at=timezone.now(), attrs={"quantity_kg": 1500})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="sample",
                            occurred_at=timezone.now(), attrs={"sample_size": 30, "avg_weight_g": 900})
    resp = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)}))
    body = resp.json()
    assert body["initial_fingerling_count"] == 2000
    assert body["mortality_count"] == 200
    assert body["current_count"] == 1800
    assert body["survival_pct"] == 90.0
    assert body["latest_avg_weight_g"] == 900.0
    assert body["fcr"] > 0
    assert body["days_in_culture"] >= 85


def test_planned_tasks_for_pond(authed, farm):
    from datetime import date, timedelta
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="pond",
        name="Pond 1", lifecycle_state="active",
        attrs={"species": "catfish", "fingerling_count": 1000,
               "stocking_date": (date.today() - timedelta(days=2)).isoformat()},
    )
    resp = authed.get(reverse("planned-tasks"))
    sources = {t["source"] for t in resp.json()["tasks"]}
    assert "pond_schedule" in sources


# ---------- Processing line (agro-processing) — M11 ----------

def test_create_processing_enterprise(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {
            "farm": str(farm.id),
            "type": "processing_line",
            "name": "Garri processing",
            "lifecycle_state": "active",
            "attrs": {"process": "cassava_garri", "input_item": "cassava",
                      "output_item": "garri", "started_on": "2026-05-01"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert Enterprise.objects.get(name="Garri processing").type == "processing_line"


def test_processing_requires_process(authed, farm):
    resp = authed.post(
        reverse("enterprises-list"),
        {"farm": str(farm.id), "type": "processing_line", "name": "X", "attrs": {}},
        format="json",
    )
    assert resp.status_code == 400
    assert "attrs" in resp.json()


def test_processing_metrics_compute_yield_ratio(authed, farm):
    from apps.activities.models import Activity
    from django.utils import timezone
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="processing_line",
        name="Garri processing", lifecycle_state="active",
        attrs={"process": "cassava_garri", "input_item": "cassava", "output_item": "garri"},
    )
    # 1000 kg cassava → 250 kg garri (two runs), yield 0.25.
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="process",
                            occurred_at=timezone.now(), attrs={"input_kg": 600, "output_kg": 150})
    Activity.objects.create(enterprise=ent, tenant_id=ent.tenant_id, type="process",
                            occurred_at=timezone.now(), attrs={"input_kg": 400, "output_kg": 100})
    resp = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)}))
    body = resp.json()
    assert body["runs_count"] == 2
    assert body["total_input_kg"] == 1000.0
    assert body["total_output_kg"] == 250.0
    assert body["yield_ratio"] == 0.25
    assert body["process"] == "cassava_garri"


# ---------- Enterprise plan ----------

def _crop_ent(farm):
    return Enterprise.objects.create(
        tenant_id=farm.id, farm=farm,
        type=Enterprise.TYPE_CROP, name="Maize Block A",
        lifecycle_state=Enterprise.LIFECYCLE_ACTIVE,
        attrs={"crop": "maize", "variety": "SAMMAZ 15", "area_ha": 1.6,
               "planting_date": "2026-04-12"},
    )


def test_plan_get_creates_and_autoseeds_plan(authed, farm):
    # First GET creates the plan AND auto-generates a cost breakdown +
    # expected outcome (the budget sibling of materializing the calendar).
    ent = _crop_ent(farm)
    resp = authed.get(reverse("enterprises-plan", kwargs={"pk": str(ent.id)}))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["budget_lines"]) == 6
    assert body["total_budget_kobo"] == sum(
        l["planned_kobo"] for l in body["budget_lines"])
    assert body["total_budget_kobo"] > 0
    assert body["expected_revenue_kobo"] > 0  # outcome seeded for maize
    assert body["is_locked"] is False


def test_plan_patch_persists_and_computes_money(authed, farm):
    ent = _crop_ent(farm)
    payload = {
        "budget_lines": [
            {"id": "fert",   "label": "Fertilizer",       "icon": "seed",    "planned_kobo": 42_000_000},
            {"id": "labour", "label": "Labour",           "icon": "team",    "planned_kobo": 38_000_000},
            {"id": "seed",   "label": "Seeds",            "icon": "seed",    "planned_kobo":  9_500_000},
        ],
        "expected_yield_kg": "8000",
        "expected_unit_price_kobo": 48_000,  # ₦480/kg
        "price_reference": "Iseyin market avg.",
    }
    resp = authed.patch(
        reverse("enterprises-plan", kwargs={"pk": str(ent.id)}),
        payload, format="json",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["total_budget_kobo"] == 89_500_000
    # 8000 kg × ₦480/kg = ₦3,840,000 = 384,000,000 kobo
    assert body["expected_revenue_kobo"] == 384_000_000
    assert body["expected_profit_kobo"] == 294_500_000
    # Break-even = 89,500,000 / 8000 = 11,187.5 → int → 11,187 kobo (~₦112/kg)
    assert body["break_even_unit_price_kobo"] == 11_187
    # ROI = 294.5M / 89.5M ≈ 329.1%
    assert body["roi_pct"] == 329.1


def test_plan_validates_line_shape(authed, farm):
    ent = _crop_ent(farm)
    resp = authed.patch(
        reverse("enterprises-plan", kwargs={"pk": str(ent.id)}),
        {"budget_lines": [{"label": "bad"}]},  # missing id + planned_kobo
        format="json",
    )
    assert resp.status_code == 400


def test_plan_lock_blocks_further_edits(authed, farm):
    from django.utils import timezone
    ent = _crop_ent(farm)
    authed.patch(
        reverse("enterprises-plan", kwargs={"pk": str(ent.id)}),
        {"locked_at": timezone.now().isoformat()}, format="json",
    )
    # Now an edit should be refused.
    refused = authed.patch(
        reverse("enterprises-plan", kwargs={"pk": str(ent.id)}),
        {"budget_lines": [
            {"id": "x", "label": "X", "planned_kobo": 1},
        ]}, format="json",
    )
    assert refused.status_code in (401, 403), refused.content
    # Unlocking + editing in the same patch should work.
    unlocked = authed.patch(
        reverse("enterprises-plan", kwargs={"pk": str(ent.id)}),
        {"locked_at": None,
         "budget_lines": [{"id": "x", "label": "X", "planned_kobo": 1}]},
        format="json",
    )
    assert unlocked.status_code == 200, unlocked.content
    assert unlocked.json()["is_locked"] is False


# ---------- Season tasks (GAP calendar → assignable, completable) ----------

def _maize(farm, planting_date):
    return Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle", name="Block A · Maize",
        lifecycle_state="active",
        attrs={"crop": "maize", "area_ha": 5.0, "planting_date": planting_date},
    )


def test_season_tasks_materialized_on_first_list(authed, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    resp = authed.get(reverse("season-tasks-list"))
    assert resp.status_code == 200
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    types = {r["activity_type"] for r in rows}
    # maize GAP template covers the full season
    assert {"land_prep", "planting", "weeding", "fertilizing", "harvesting"} <= types


def test_season_tasks_are_idempotent(authed, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    first = authed.get(reverse("season-tasks-list")).json()
    second = authed.get(reverse("season-tasks-list")).json()
    a = first["results"] if isinstance(first, dict) else first
    b = second["results"] if isinstance(second, dict) else second
    assert len(a) == len(b)  # listing twice doesn't duplicate


def test_manager_assigns_task_to_field_staff(authed, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    hand = User.objects.create_user(phone="+2348010000044")
    StaffMembership.objects.create(user=hand, farm=farm, role=StaffMembership.ROLE_FIELD)
    task_id = (authed.get(reverse("season-tasks-list")).json()
               ["results"] if isinstance(authed.get(reverse("season-tasks-list")).json(), dict)
               else authed.get(reverse("season-tasks-list")).json())[0]["id"]
    resp = authed.post(reverse("season-tasks-assign", kwargs={"pk": task_id}),
                       {"assignee": str(hand.id)}, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["assigned_to"] == str(hand.id)


def test_field_staff_cannot_assign(api_client, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    hand = User.objects.create_user(phone="+2348010000045")
    StaffMembership.objects.create(user=hand, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=hand)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    rows = api_client.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    resp = api_client.post(reverse("season-tasks-assign", kwargs={"pk": rows[0]["id"]}),
                           {"assignee": str(hand.id)}, format="json")
    assert resp.status_code == 403


def test_assigned_to_me_filter(api_client, owner, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    hand = User.objects.create_user(phone="+2348010000046")
    StaffMembership.objects.create(user=hand, farm=farm, role=StaffMembership.ROLE_FIELD)
    # owner lists + assigns the first task to the hand
    owner_c = api_client
    owner_c.force_authenticate(user=owner)
    owner_c.credentials(HTTP_X_TENANT_ID=str(farm.id))
    rows = owner_c.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    owner_c.post(reverse("season-tasks-assign", kwargs={"pk": rows[0]["id"]}),
                 {"assignee": str(hand.id)}, format="json")
    # hand sees exactly that one in their worklist
    api_client.force_authenticate(user=hand)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    mine = api_client.get(reverse("season-tasks-list"), {"assigned_to_me": "true"}).json()
    mine = mine["results"] if isinstance(mine, dict) else mine
    assert len(mine) == 1


def test_quick_complete(authed, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    rows = authed.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    pending = [r for r in rows if r["status"] == "pending"][0]
    resp = authed.post(reverse("season-tasks-complete", kwargs={"pk": pending["id"]}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    assert resp.json()["completed_at"] is not None


def test_logging_activity_auto_completes_matching_task(authed, farm):
    """The core loop: a farm hand logs an activity → the matching GAP task is done."""
    from datetime import date
    from apps.activities.models import Activity
    from apps.enterprises.models import SeasonTask
    from django.utils import timezone
    ent = _maize(farm, date.today().isoformat())
    authed.get(reverse("season-tasks-list"))  # materialize

    # The 'planting' slot is at day 0 (today). Log a planting activity.
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="planting",
        occurred_at=timezone.now(),
    )
    task = SeasonTask.objects.get(enterprise=ent, activity_type="planting")
    assert task.status == "done"
    assert task.completed_activity is not None


def test_regenerate_after_planting_date_change(authed, farm):
    from datetime import date, timedelta
    from apps.enterprises.models import SeasonTask
    ent = _maize(farm, date.today().isoformat())
    authed.get(reverse("season-tasks-list"))
    original_dates = sorted(
        SeasonTask.objects.filter(enterprise=ent).values_list("target_date", flat=True)
    )
    # Move planting two weeks later and regenerate.
    ent.attrs = {**ent.attrs, "planting_date": (date.today() + timedelta(days=14)).isoformat()}
    ent.save(update_fields=["attrs"])
    resp = authed.post(reverse("season-tasks-generate"), {"enterprise": str(ent.id)}, format="json")
    assert resp.status_code == 200, resp.content
    new_dates = sorted(SeasonTask.objects.filter(enterprise=ent).values_list("target_date", flat=True))
    assert new_dates != original_dates  # shifted with the new planting date


# ---------- expanded crop templates + task CRUD ----------

def test_yam_template_generates_full_season(authed, farm):
    from datetime import date
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle", name="Yam plot",
        lifecycle_state="active",
        attrs={"crop": "yam", "area_ha": 1.0, "planting_date": date.today().isoformat()},
    )
    rows = authed.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    types = {r["activity_type"] for r in rows}
    assert {"land_prep", "planting", "staking", "harvesting"} <= types


def test_sorghum_template_exists(authed, farm):
    from datetime import date
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle", name="Sorghum",
        lifecycle_state="active",
        attrs={"crop": "sorghum", "area_ha": 2.0, "planting_date": date.today().isoformat()},
    )
    rows = authed.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert len(rows) >= 6


def test_unknown_crop_uses_generic_template(authed, farm):
    from datetime import date
    Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle", name="Sesame",
        lifecycle_state="active",
        attrs={"crop": "sesame", "area_ha": 1.0, "planting_date": date.today().isoformat()},
    )
    rows = authed.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    types = {r["activity_type"] for r in rows}
    # generic field-crop cycle still gives a usable starting schedule
    assert {"land_prep", "planting", "weeding", "harvesting"} <= types


def test_add_custom_task(authed, farm):
    from datetime import date, timedelta
    ent = _maize(farm, date.today().isoformat())
    authed.get(reverse("season-tasks-list"))  # materialize
    resp = authed.post(reverse("season-tasks-add"), {
        "enterprise": str(ent.id),
        "label": "Bird scaring",
        "activity_type": "scouting",
        "target_date": (date.today() + timedelta(days=80)).isoformat(),
    }, format="json")
    assert resp.status_code == 201, resp.content
    assert resp.json()["label"] == "Bird scaring"
    assert resp.json()["source"] == "custom"


def test_edit_task_label_and_date(authed, farm):
    from datetime import date, timedelta
    _maize(farm, date.today().isoformat())
    rows = authed.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    tid = rows[0]["id"]
    new_date = (date.today() + timedelta(days=3)).isoformat()
    resp = authed.patch(reverse("season-tasks-edit", kwargs={"pk": tid}),
                        {"label": "Renamed task", "target_date": new_date}, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["label"] == "Renamed task"
    assert resp.json()["target_date"] == new_date


def test_delete_task(authed, farm):
    from datetime import date
    from apps.enterprises.models import SeasonTask
    _maize(farm, date.today().isoformat())
    rows = authed.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    tid = rows[0]["id"]
    resp = authed.delete(reverse("season-tasks-remove", kwargs={"pk": tid}))
    assert resp.status_code == 204
    assert not SeasonTask.objects.filter(pk=tid).exists()


def test_field_staff_cannot_edit_task(api_client, farm):
    from datetime import date
    _maize(farm, date.today().isoformat())
    hand = User.objects.create_user(phone="+2348010000088")
    StaffMembership.objects.create(user=hand, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=hand)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    rows = api_client.get(reverse("season-tasks-list")).json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    resp = api_client.patch(reverse("season-tasks-edit", kwargs={"pk": rows[0]["id"]}),
                            {"label": "hax"}, format="json")
    assert resp.status_code == 403

# ===== Broiler breed standards + flock projection metrics =====

def test_broiler_standard_lookup_normalizes_breed():
    from apps.enterprises.broiler_standards import standard_for
    assert standard_for("Cobb 500")["label"] == "Cobb 500"
    assert standard_for("cobb-500")["label"] == "Cobb 500"
    assert standard_for("ross_308")["label"] == "Ross 308"


def test_broiler_unknown_breed_falls_back_to_generic():
    from apps.enterprises.broiler_standards import standard_for
    assert standard_for("noiler")["label"] == "Broiler"
    assert standard_for(None)["label"] == "Broiler"


def test_broiler_target_weight_interpolates_and_clamps():
    from apps.enterprises.broiler_standards import target_weight_g
    assert 185 < target_weight_g("cobb_500", 10) < 465
    assert target_weight_g("cobb_500", 0) == 42
    assert target_weight_g("cobb_500", 999) == target_weight_g("cobb_500", 56)


def test_broiler_resolve_targets_hybrid_overrides():
    from apps.enterprises.broiler_standards import resolve_targets
    t = resolve_targets({"breed": "cobb_500", "target_fcr": 1.5, "cycle_length_days": 49})
    assert t["target_fcr"] == 1.5
    assert t["cycle_length_days"] == 49
    assert t["target_market_weight_g"] == 2700


def _broiler_ent(farm, **extra):
    from datetime import timedelta
    from django.utils import timezone
    stocking = (timezone.now() - timedelta(days=14)).date().isoformat()
    attrs = {"kind": "broiler", "breed": "cobb_500", "bird_count": 1000,
             "stocking_date": stocking}
    attrs.update(extra)
    return Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="flock", name="Pen 3",
        attrs=attrs, lifecycle_state="active",
    )


def test_flock_metrics_expose_targets_and_breed(authed, farm):
    ent = _broiler_ent(farm)
    body = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)})).json()
    assert body["name"] == "Pen 3"
    assert body["breed_label"] == "Cobb 500"
    assert body["cycle_length"] == 56
    assert body["targets"]["fcr"] == 1.65
    assert body["targets"]["market_weight_g"] == 2700
    assert any(p["day"] == 56 for p in body["weight_series"])


def test_flock_weight_series_actual_matches_sample(authed, farm):
    from apps.activities.models import Activity
    from django.utils import timezone
    ent = _broiler_ent(farm)
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
        occurred_at=timezone.now(), attrs={"sample_size": 20, "avg_weight_g": 470},
    )
    body = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)})).json()
    series = {p["day"]: p for p in body["weight_series"]}
    assert series[14]["actual_g"] == 470
    assert series[14]["target_g"] is not None
    assert series[56]["actual_g"] is None


def test_flock_projected_economics_with_price(authed, farm):
    from datetime import timedelta
    from apps.activities.models import Activity
    from django.utils import timezone
    ent = _broiler_ent(
        farm,
        stocking_date=(timezone.now() - timedelta(days=21)).date().isoformat(),
        sale_price_per_kg=1800,
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
        occurred_at=timezone.now() - timedelta(days=7),
        attrs={"sample_size": 20, "avg_weight_g": 300},
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
        occurred_at=timezone.now(), attrs={"sample_size": 20, "avg_weight_g": 600},
    )
    body = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)})).json()
    assert body["projected_revenue_kobo"] is not None
    assert body["projected_profit_kobo"] is not None
    assert body["plan_delta_kobo"] is not None
    assert body["insight"]


def test_flock_without_price_prompts_for_one(authed, farm):
    from datetime import timedelta
    from apps.activities.models import Activity
    from django.utils import timezone
    ent = _broiler_ent(
        farm,
        stocking_date=(timezone.now() - timedelta(days=21)).date().isoformat(),
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
        occurred_at=timezone.now() - timedelta(days=7),
        attrs={"sample_size": 20, "avg_weight_g": 300},
    )
    Activity.objects.create(
        enterprise=ent, tenant_id=ent.tenant_id, type="weigh",
        occurred_at=timezone.now(), attrs={"sample_size": 20, "avg_weight_g": 600},
    )
    body = authed.get(reverse("enterprises-metrics", kwargs={"pk": str(ent.id)})).json()
    assert body["projected_revenue_kobo"] is None
    assert "sale price" in body["insight"].lower()

# ===== Auto-generated cost-breakdown (budget) estimates =====

def test_budget_lines_scale_by_area_for_crops():
    from apps.enterprises.budget_templates import budget_lines_for

    class _E:
        type = 'crop_cycle'
        attrs = {'crop': 'maize', 'area_ha': 2.0}

    lines = budget_lines_for(_E())
    assert len(lines) == 6
    seed = next(l for l in lines if l['id'] == 'seed')
    # Maize seed is ₦25,000/ha → ₦50,000 for 2 ha (5,000,000 kobo).
    assert seed['planned_kobo'] == 5_000_000
    assert all('label' in l and 'icon' in l for l in lines)


def test_budget_lines_scale_per_100_birds_for_flock():
    from apps.enterprises.budget_templates import budget_lines_for

    class _E:
        type = 'flock'
        attrs = {'kind': 'broiler', 'bird_count': 500}

    lines = budget_lines_for(_E())
    feed = next(l for l in lines if l['id'] == 'feed')
    # Broiler feed ₦240,000/100 birds → ×5 for 500 birds = 120,000,000 kobo.
    assert feed['planned_kobo'] == 120_000_000


def test_budget_lines_for_herd_and_pond_and_unknown():
    from apps.enterprises.budget_templates import budget_lines_for

    class _Herd:
        type = 'herd'; attrs = {'herd_size': 50}
    class _Pond:
        type = 'pond'; attrs = {'fingerling_count': 1000}
    class _Proc:
        type = 'processing_line'; attrs = {}

    assert budget_lines_for(_Herd())  # scaled ×0.5
    assert budget_lines_for(_Pond())  # scaled ×10
    assert budget_lines_for(_Proc()) == []  # no template → empty


def test_plan_get_autogenerates_budget_and_money_to_spend(authed, farm):
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type='crop_cycle', name='Block A',
        attrs={'crop': 'maize', 'area_ha': 5.0}, lifecycle_state='active',
    )
    body = authed.get(reverse('enterprises-plan', kwargs={'pk': str(ent.id)})).json()
    assert len(body['budget_lines']) == 6
    # money to spend = sum of the generated lines
    assert body['total_budget_kobo'] == sum(l['planned_kobo'] for l in body['budget_lines'])
    assert body['total_budget_kobo'] > 0
    # expected outcome seeded → revenue + ROI computed
    assert body['expected_revenue_kobo'] > 0
    assert body['roi_pct'] is not None


def test_plan_autogeneration_is_idempotent(authed, farm):
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type='flock', name='Pen 1',
        attrs={'kind': 'broiler', 'bird_count': 300}, lifecycle_state='active',
    )
    url = reverse('enterprises-plan', kwargs={'pk': str(ent.id)})
    first = authed.get(url).json()
    second = authed.get(url).json()
    assert first['budget_lines'] == second['budget_lines']
    assert len(second['budget_lines']) == 6  # not doubled


def test_plan_autogeneration_does_not_overwrite_edits(authed, farm):
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type='crop_cycle', name='Block B',
        attrs={'crop': 'maize', 'area_ha': 1.0}, lifecycle_state='active',
    )
    url = reverse('enterprises-plan', kwargs={'pk': str(ent.id)})
    authed.get(url)  # seeds
    custom = [{'id': 'mine', 'label': 'My only cost', 'icon': 'more', 'planned_kobo': 123456}]
    authed.patch(url, {'budget_lines': custom}, format='json')
    body = authed.get(url).json()
    assert body['budget_lines'] == custom  # not re-seeded


def test_ensure_plan_budget_skips_locked_plan(db, farm):
    from django.utils import timezone
    from apps.enterprises.models import EnterprisePlan
    from apps.enterprises.budget_templates import ensure_plan_budget
    ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type='crop_cycle', name='Block C',
        attrs={'crop': 'maize', 'area_ha': 1.0},
    )
    plan = EnterprisePlan.objects.create(
        enterprise=ent, tenant_id=farm.id, locked_at=timezone.now(),
    )
    assert ensure_plan_budget(plan, ent) is False
    assert plan.budget_lines == []
