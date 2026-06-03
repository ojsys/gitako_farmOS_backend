"""M12 AI co-pilot — stub provider routing, farm-scoped tools, anomalies, API."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.copilot import service
from apps.copilot.tools import make_executor
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.finance.models import Account, Transaction
from apps.inventory.models import InventoryItem, InventoryMovement, Store
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(phone="+2348010000001", full_name="Lekan")


@pytest.fixture
def farm(owner):
    f = Farm.objects.create(name="Test Farm", owner=owner)
    StaffMembership.objects.create(user=owner, farm=f, role=StaffMembership.ROLE_OWNER)
    return f


@pytest.fixture
def authed(api_client, owner, farm):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    return api_client


def _seed_money(farm):
    acc = Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash", type="cash",
                                 opening_balance_kobo=0)
    Transaction.objects.create(tenant_id=farm.id, farm=farm, account=acc, kind="income",
                               amount_kobo=500_000_00, posted_at=timezone.now())
    Transaction.objects.create(tenant_id=farm.id, farm=farm, account=acc, kind="expense",
                               amount_kobo=-200_000_00, posted_at=timezone.now())
    return acc


# ---------- stub chat routing ----------

def test_chat_routes_money_question_to_financial_tool(authed, farm):
    _seed_money(farm)
    resp = authed.post(reverse("copilot-chat"), {"message": "How is my cash position?"}, format="json")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "get_financial_summary" in body["used_tools"]
    assert "₦" in body["reply"]


def test_chat_routes_performance_question_to_metrics(authed, farm):
    Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type="flock", name="Pen 3",
        lifecycle_state="active", attrs={"kind": "broiler", "bird_count": 1000,
                                         "stocking_date": "2026-05-01"},
    )
    resp = authed.post(reverse("copilot-chat"), {"message": "What is my flock mortality?"}, format="json")
    body = resp.json()
    assert "get_enterprise_metrics" in body["used_tools"]
    assert "Pen 3" in body["reply"]


def test_chat_routes_stock_question(authed, farm):
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    item = InventoryItem.objects.create(tenant_id=farm.id, farm=farm, name="Feed", unit="bags",
                                        reorder_level=10)
    InventoryMovement.objects.create(tenant_id=farm.id, item=item, store=store, op="receipt",
                                     qty=3, unit_cost_kobo=100000, occurred_at=timezone.now())
    resp = authed.post(reverse("copilot-chat"), {"message": "Am I running low on stock?"}, format="json")
    body = resp.json()
    assert "get_low_stock" in body["used_tools"]
    assert "Feed" in body["reply"]


def test_chat_unknown_question_gives_help(authed, farm):
    resp = authed.post(reverse("copilot-chat"), {"message": "Tell me a joke"}, format="json")
    body = resp.json()
    assert body["used_tools"] == []


def test_chat_requires_message(authed):
    resp = authed.post(reverse("copilot-chat"), {"message": "  "}, format="json")
    assert resp.status_code == 400


def test_chat_requires_tenant(api_client, owner):
    api_client.force_authenticate(user=owner)
    resp = api_client.post(reverse("copilot-chat"), {"message": "How is my cash?"}, format="json")
    assert resp.status_code == 403


# ---------- tools executor ----------

def test_create_reminder_tool_makes_notification(farm, owner):
    execute = make_executor(farm, owner)
    out = execute("create_reminder", {"title": "Order feed", "days_from_now": 2})
    assert "Order feed" in out
    assert Notification.objects.filter(user=owner, title="Order feed").exists()


# ---------- anomalies ----------

def test_anomalies_flags_mortality_spike(authed, farm):
    ent = Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type="flock", name="Pen 4",
        lifecycle_state="active", attrs={"kind": "broiler", "bird_count": 1000,
                                         "stocking_date": "2026-05-01"},
    )
    Activity.objects.create(tenant_id=farm.id, enterprise=ent, type="mortality",
                            occurred_at=timezone.now(), attrs={"count": 80})  # 8%
    resp = authed.get(reverse("copilot-anomalies"))
    types = {a["type"] for a in resp.json()["anomalies"]}
    assert "mortality_spike" in types


def test_anomalies_empty_when_healthy(authed, farm):
    resp = authed.get(reverse("copilot-anomalies"))
    assert resp.json()["anomalies"] == []


# ---------- diagnose (stub) ----------

def test_diagnose_stub_returns_guidance(authed):
    resp = authed.post(reverse("copilot-diagnose"),
                       {"image_base64": "Zm9v", "media_type": "image/jpeg"}, format="json")
    assert resp.status_code == 200
    assert "stub" in resp.json()


def test_diagnose_rejects_bad_media_type(authed):
    resp = authed.post(reverse("copilot-diagnose"),
                       {"image_base64": "Zm9v", "media_type": "application/pdf"}, format="json")
    assert resp.status_code == 400


def test_service_answer_question_direct(farm, owner):
    _seed_money(farm)
    result = service.answer_question(farm=farm, user=owner, message="show me the profit")
    assert "get_financial_summary" in result["used_tools"]
