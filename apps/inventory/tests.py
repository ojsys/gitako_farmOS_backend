"""Inventory CRUD + stock math + transfer + summary tests."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.farms.models import Farm, StaffMembership
from apps.inventory.models import InventoryItem, InventoryMovement, Store

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(phone="+2348010000001")


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


def test_create_store_and_item(authed, farm):
    s = authed.post(reverse("stores-list"), {"name": "Main store"}, format="json")
    assert s.status_code == 201, s.content
    assert Store.objects.filter(farm=farm, name="Main store").exists()

    i = authed.post(
        reverse("inventory-items-list"),
        {"name": "NPK 20-10-10", "category": "fertilizer", "unit": "bags",
         "reorder_level": "5"},
        format="json",
    )
    assert i.status_code == 201, i.content
    assert InventoryItem.objects.filter(farm=farm, name="NPK 20-10-10").exists()


def test_receipt_then_issue_computes_stock(authed, farm):
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="NPK", category="fertilizer", unit="bags",
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op="receipt",
        qty=10, unit_cost_kobo=2_300_000, occurred_at=timezone.now(),
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op="issue",
        qty=-3, occurred_at=timezone.now(),
    )
    resp = authed.get(reverse("inventory-items-stock", kwargs={"pk": str(item.id)}))
    body = resp.json()
    assert body["qty_on_hand"] == 7.0
    # 10 bags received at 2,300,000 kobo (₦23,000) each.
    # After issuing 3, remaining 7 bags × 2,300,000 = 16,100,000 kobo.
    assert body["value_kobo"] == 16_100_000


def test_low_stock_flag(authed, farm):
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="Urea", category="fertilizer",
        unit="bags", reorder_level=5,
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op="receipt",
        qty=3, unit_cost_kobo=2_350_000, occurred_at=timezone.now(),
    )
    resp = authed.get(reverse("inventory-items-detail", kwargs={"pk": str(item.id)}))
    body = resp.json()
    assert body["is_low_stock"] is True
    assert body["on_hand"] == 3.0


def test_transfer_creates_paired_movements(authed, farm):
    src = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    dst = Store.objects.create(tenant_id=farm.id, farm=farm, name="Shed")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="Seed", category="seed", unit="kg",
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=src, op="receipt",
        qty=50, unit_cost_kobo=1_200_00, occurred_at=timezone.now(),
    )
    resp = authed.post(
        reverse("inventory-movements-transfer"),
        {"item": str(item.id), "from_store": str(src.id),
         "to_store": str(dst.id), "qty": 20},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    rows = resp.json()
    assert len(rows) == 2
    # Both movements should share the same transfer_pair_id.
    assert rows[0]["transfer_pair_id"] == rows[1]["transfer_pair_id"]
    # Source store now has 30, destination has 20.
    src_qty = sum(float(m.qty) for m in src.movements.all())
    dst_qty = sum(float(m.qty) for m in dst.movements.all())
    assert src_qty == 30.0
    assert dst_qty == 20.0


def test_summary_endpoint(authed, farm):
    s1 = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    Store.objects.create(tenant_id=farm.id, farm=farm, name="Shed")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="NPK", category="fertilizer",
        unit="bags", reorder_level=5,
    )
    InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=s1, op="receipt",
        qty=10, unit_cost_kobo=2_300_000, occurred_at=timezone.now(),
    )
    resp = authed.get(reverse("inventory-summary-list"))
    body = resp.json()
    assert body["store_count"] == 2
    assert body["item_count"] == 1
    assert body["total_value_kobo"] == 10 * 2_300_000
    assert body["low_stock_count"] == 0


def test_viewer_cannot_create_inventory(api_client, farm):
    viewer = User.objects.create_user(phone="+2348019998888")
    StaffMembership.objects.create(user=viewer, farm=farm, role=StaffMembership.ROLE_VIEWER)
    api_client.force_authenticate(user=viewer)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("stores-list"), {"name": "X"}, format="json")
    assert resp.status_code == 403


def test_field_staff_can_create_inventory(api_client, farm):
    """Field staff can record movements & items (they're operational, not
    farm-structural). Only farm/staff/enterprise creation is gated to managers."""
    field = User.objects.create_user(phone="+2348019997777")
    StaffMembership.objects.create(user=field, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=field)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("stores-list"), {"name": "Y"}, format="json")
    assert resp.status_code == 201, resp.content


def test_movement_via_sync_push(authed, farm):
    """Inventory movements registered in the sync allow-list."""
    import uuid as _uuid
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="NPK", category="fertilizer", unit="bags",
    )
    row_id = str(_uuid.uuid4())
    resp = authed.post(
        reverse("sync-push"),
        {
            "ops": [
                {
                    "table": "inventory_inventorymovement",
                    "row_id": row_id,
                    "op": "insert",
                    "payload": {
                        "item": str(item.id),
                        "store": str(store.id),
                        "op": "receipt",
                        "qty": "5",
                        "unit_cost_kobo": 2_500_000,
                        "occurred_at": timezone.now().isoformat(),
                    },
                    "client_seq": 1,
                }
            ],
        },
        format="json",
        HTTP_X_DEVICE_ID="dev-1",
    )
    assert resp.status_code == 200, resp.content
    assert InventoryMovement.objects.filter(pk=row_id, item=item).exists()
