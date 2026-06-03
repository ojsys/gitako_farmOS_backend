"""M19 USSD — menu state machine, balance, alerts, activity logging."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.finance.models import Account, Transaction
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

PHONE = "+2348010000001"


@pytest.fixture
def owner():
    return User.objects.create_user(phone=PHONE)


@pytest.fixture
def farm(owner):
    f = Farm.objects.create(name="Lekan Farms", owner=owner)
    StaffMembership.objects.create(user=owner, farm=f, role=StaffMembership.ROLE_OWNER)
    return f


def _post(api_client, text):
    return api_client.post(reverse("ussd-gateway"),
                           {"phoneNumber": PHONE, "text": text}, format="json")


def test_unregistered_number(api_client):
    resp = api_client.post(reverse("ussd-gateway"),
                           {"phoneNumber": "+2349999999999", "text": ""}, format="json")
    assert resp.data.startswith("END")
    assert "not registered" in resp.data


def test_top_menu(api_client, farm):
    resp = _post(api_client, "")
    assert resp.data.startswith("CON")
    assert "cash balance" in resp.data
    assert "Log an activity" in resp.data


def test_balance_option(api_client, owner, farm):
    acc = Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash", type="cash")
    Transaction.objects.create(tenant_id=farm.id, farm=farm, account=acc, kind="income",
                               amount_kobo=250_000_00, posted_at=timezone.now())
    resp = _post(api_client, "1")
    assert resp.data.startswith("END")
    assert "Net position" in resp.data


def test_alerts_option(api_client, owner, farm):
    Notification.objects.create(user=owner, type="custom", title="Vaccinate Batch 17",
                                dedupe_key="x", is_read=False)
    resp = _post(api_client, "2")
    assert resp.data.startswith("END")
    assert "Vaccinate Batch 17" in resp.data


def test_log_activity_flow(api_client, owner, farm):
    ent = Enterprise.objects.create(tenant_id=farm.id, farm=farm, type="flock", name="Pen 3",
                                    lifecycle_state="active",
                                    attrs={"kind": "broiler", "bird_count": 1000,
                                           "stocking_date": "2026-05-01"})
    # 3 → enterprise list
    step1 = _post(api_client, "3")
    assert step1.data.startswith("CON")
    assert "Pen 3" in step1.data
    # 3*1 → activity list
    step2 = _post(api_client, "3*1")
    assert step2.data.startswith("CON")
    assert "Feed" in step2.data
    # 3*1*1 → record Feed
    step3 = _post(api_client, "3*1*1")
    assert step3.data.startswith("END")
    assert "Recorded" in step3.data
    assert Activity.objects.filter(enterprise=ent, type="feed", notes="Logged via USSD").exists()


def test_invalid_choice(api_client, farm):
    resp = _post(api_client, "9")
    assert resp.data.startswith("END")
    assert "Invalid" in resp.data
