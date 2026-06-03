"""M8 notifications — dispatch idempotency, channel routing, threshold engine,
digest scheduling, and the REST surface."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.inventory.models import InventoryItem, InventoryMovement, Store
from apps.notifications import engine
from apps.notifications.dispatch import notify
from apps.notifications.models import (
    DigestPreference,
    Notification,
    NotificationRule,
)

pytestmark = pytest.mark.django_db


# ---------- fixtures ----------

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


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, *, phone, message):
        self.sent.append((phone, message))


@pytest.fixture
def fake_channels(monkeypatch):
    sms = FakeSms()
    monkeypatch.setattr("apps.notifications.dispatch.get_sms_provider", lambda: sms)
    return sms


# ---------- dispatch ----------

def test_notify_is_idempotent(owner, fake_channels):
    first = notify(user=owner, type=Notification.TYPE_CUSTOM, title="Hi", dedupe_key="k1")
    second = notify(user=owner, type=Notification.TYPE_CUSTOM, title="Hi", dedupe_key="k1")
    assert first.created is True
    assert second.created is False
    assert Notification.objects.filter(user=owner, dedupe_key="k1").count() == 1


def test_sms_only_on_requested_channel(owner, fake_channels):
    sms = fake_channels

    notify(user=owner, type=Notification.TYPE_CUSTOM, title="In-app only", dedupe_key="a",
           channels=("in_app",))
    assert sms.sent == []

    notify(user=owner, type=Notification.TYPE_CUSTOM, title="With SMS", dedupe_key="b",
           channels=("in_app", "sms"))
    assert len(sms.sent) == 1


# ---------- threshold engine ----------

def test_mortality_alert_fires_above_threshold(owner, farm, fake_channels):
    sms = fake_channels
    ent = Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type=Enterprise.TYPE_FLOCK,
        name="Pen 3 Broilers", lifecycle_state="active",
        attrs={"kind": "broiler", "bird_count": 1000, "stocking_date": "2026-05-01"},
    )
    Activity.objects.create(
        tenant_id=farm.id, enterprise=ent, type="mortality",
        occurred_at=timezone.now(), attrs={"count": 60},  # 6% > 5% default
    )
    created = engine.run_threshold_alerts()
    assert created >= 1
    note = Notification.objects.get(user=owner, type=Notification.TYPE_MORTALITY)
    assert "Pen 3" in note.title
    # Mortality is a critical rule → SMS fires.
    assert len(sms.sent) == 1


def test_no_mortality_alert_below_threshold(owner, farm, fake_channels):
    ent = Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type=Enterprise.TYPE_FLOCK,
        name="Pen 4", lifecycle_state="active",
        attrs={"kind": "broiler", "bird_count": 1000, "stocking_date": "2026-05-01"},
    )
    Activity.objects.create(
        tenant_id=farm.id, enterprise=ent, type="mortality",
        occurred_at=timezone.now(), attrs={"count": 20},  # 2% < 5%
    )
    engine.run_threshold_alerts()
    assert not Notification.objects.filter(type=Notification.TYPE_MORTALITY).exists()


def test_mortality_alert_fires_for_herd(owner, farm, fake_channels):
    ent = Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type=Enterprise.TYPE_HERD,
        name="Goat herd", lifecycle_state="active",
        attrs={"species": "goat", "herd_size": 100, "acquisition_date": "2026-03-01"},
    )
    Activity.objects.create(
        tenant_id=farm.id, enterprise=ent, type="mortality",
        occurred_at=timezone.now(), attrs={"count": 8},  # 8% > 5% default
    )
    engine.run_threshold_alerts()
    assert Notification.objects.filter(user=owner, type=Notification.TYPE_MORTALITY).exists()


def test_low_stock_alert(owner, farm, fake_channels):
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main store")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="Grower feed", unit="bags", reorder_level=10,
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op=InventoryMovement.OP_RECEIPT,
        qty=5, unit_cost_kobo=500000, occurred_at=timezone.now(),
    )
    engine.run_threshold_alerts()
    assert Notification.objects.filter(user=owner, type=Notification.TYPE_LOW_STOCK).count() == 1


def test_overdue_activity_alert(owner, farm, fake_channels):
    Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type=Enterprise.TYPE_CROP,
        name="Block A Maize", lifecycle_state="active",
        attrs={"crop": "maize", "area_ha": 5,
               "planting_date": (timezone.localdate() - timedelta(days=20)).isoformat()},
    )
    created = engine.run_threshold_alerts()
    assert created >= 1
    assert Notification.objects.filter(user=owner, type=Notification.TYPE_OVERDUE).exists()


def test_calendar_reminder_for_upcoming_task(owner, farm, fake_channels):
    Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type=Enterprise.TYPE_CROP,
        name="Block B Maize", lifecycle_state="active",
        attrs={"crop": "maize", "area_ha": 3,
               "planting_date": timezone.localdate().isoformat()},
    )
    created = engine.run_calendar_reminders()
    assert created >= 1
    assert Notification.objects.filter(user=owner, type=Notification.TYPE_CALENDAR).exists()


def test_alerts_are_idempotent_across_runs(owner, farm, fake_channels):
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main store")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="Grower feed", unit="bags", reorder_level=10,
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op=InventoryMovement.OP_RECEIPT,
        qty=5, unit_cost_kobo=500000, occurred_at=timezone.now(),
    )
    engine.run_threshold_alerts()
    engine.run_threshold_alerts()
    assert Notification.objects.filter(type=Notification.TYPE_LOW_STOCK).count() == 1


def test_disabled_rule_suppresses_alert(owner, farm, fake_channels):
    NotificationRule.objects.create(
        farm=farm, rule_type=NotificationRule.RULE_LOW_STOCK, enabled=False,
    )
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main store")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="Grower feed", unit="bags", reorder_level=10,
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op=InventoryMovement.OP_RECEIPT,
        qty=5, unit_cost_kobo=500000, occurred_at=timezone.now(),
    )
    engine.run_threshold_alerts()
    assert not Notification.objects.filter(type=Notification.TYPE_LOW_STOCK).exists()


# ---------- digest ----------

def test_daily_digest_respects_hour_and_dedupe(owner, fake_channels):
    now = timezone.localtime()
    DigestPreference.objects.create(user=owner, enabled=True, send_hour=now.hour)
    assert engine.run_daily_digest(now=now) == 1
    # Second run the same day is a no-op.
    assert engine.run_daily_digest(now=now) == 0
    assert Notification.objects.filter(user=owner, type=Notification.TYPE_DIGEST).count() == 1


def test_daily_digest_skips_other_hours(owner, fake_channels):
    now = timezone.localtime()
    DigestPreference.objects.create(user=owner, enabled=True, send_hour=(now.hour + 1) % 24)
    assert engine.run_daily_digest(now=now) == 0


# ---------- REST API ----------

def test_list_and_mark_read(authed, owner):
    Notification.objects.create(user=owner, type="custom", title="A", dedupe_key="x")
    Notification.objects.create(user=owner, type="custom", title="B", dedupe_key="y")

    resp = authed.get(reverse("notifications-list"))
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 2

    count = authed.get(reverse("notifications-unread-count")).json()
    assert count["unread"] == 2

    marked = authed.post(reverse("notifications-mark-all-read"))
    assert marked.json()["marked"] == 2
    assert Notification.objects.filter(user=owner, is_read=True).count() == 2


def test_notifications_are_user_scoped(authed, farm):
    other = User.objects.create_user(phone="+2348019999999")
    Notification.objects.create(user=other, type="custom", title="theirs", dedupe_key="z")
    resp = authed.get(reverse("notifications-list"))
    assert resp.json()["results"] == []


def test_update_digest_preference(authed, owner):
    resp = authed.patch(reverse("digest-preference"), {"send_hour": 7}, format="json")
    assert resp.status_code == 200
    assert DigestPreference.objects.get(user=owner).send_hour == 7


def test_digest_preference_rejects_bad_hour(authed):
    resp = authed.patch(reverse("digest-preference"), {"send_hour": 25}, format="json")
    assert resp.status_code == 400
