"""Finance — account balances, transactions, transfers, cash position, P&L."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.finance.models import Account, Transaction

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


def test_create_account_with_opening_balance(authed, farm):
    resp = authed.post(
        reverse("accounts-list"),
        {"name": "Cash on hand", "type": "cash", "opening_balance_kobo": 420_000_00},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["balance_kobo"] == 420_000_00


def test_expense_decreases_balance(authed, farm):
    acc = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Cash",
        opening_balance_kobo=1_000_000_00,  # ₦1,000,000
    )
    resp = authed.post(
        reverse("transactions-list"),
        {
            "account": str(acc.id),
            "kind": "expense",
            "amount_kobo": 50_000_00,  # client sends positive; server normalizes
            "description": "Bought NPK",
            "posted_at": timezone.now().isoformat(),
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    detail = authed.get(reverse("accounts-detail", kwargs={"pk": str(acc.id)})).json()
    assert detail["balance_kobo"] == 950_000_00


def test_income_increases_balance(authed, farm):
    acc = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Cash", opening_balance_kobo=0,
    )
    authed.post(
        reverse("transactions-list"),
        {
            "account": str(acc.id),
            "kind": "income",
            "amount_kobo": 128_000_00,
            "description": "Sold maize",
            "posted_at": timezone.now().isoformat(),
        },
        format="json",
    )
    detail = authed.get(reverse("accounts-detail", kwargs={"pk": str(acc.id)})).json()
    assert detail["balance_kobo"] == 128_000_00


def test_transfer_creates_paired_rows(authed, farm):
    cash = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Cash", opening_balance_kobo=200_000_00,
    )
    bank = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Bank", opening_balance_kobo=0,
    )
    resp = authed.post(
        reverse("transactions-transfer"),
        {"from_account": str(cash.id), "to_account": str(bank.id),
         "amount_kobo": 75_000_00, "description": "Deposit"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["transfer_pair_id"] == rows[1]["transfer_pair_id"]
    cash_bal = authed.get(reverse("accounts-detail", kwargs={"pk": str(cash.id)})).json()["balance_kobo"]
    bank_bal = authed.get(reverse("accounts-detail", kwargs={"pk": str(bank.id)})).json()["balance_kobo"]
    assert cash_bal == 125_000_00
    assert bank_bal == 75_000_00


def test_cash_position_endpoint(authed, farm):
    Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash",
                          opening_balance_kobo=420_000_00, type="cash")
    Account.objects.create(tenant_id=farm.id, farm=farm, name="Bank",
                          opening_balance_kobo=1_185_200_00, type="bank")
    resp = authed.get(reverse("cash-position"))
    body = resp.json()
    assert len(body["by_account"]) == 2
    assert body["total_kobo"] == 420_000_00 + 1_185_200_00


def test_pnl_endpoint_rolls_up_per_enterprise(authed, farm):
    acc = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Cash", opening_balance_kobo=0,
    )
    block_a = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle",
        name="Block A · Maize", attrs={"crop": "maize", "area_ha": 5},
        lifecycle_state="active",
    )
    # Money in: 1,925,500 on Block A
    Transaction.objects.create(
        tenant_id=farm.id, farm=farm, account=acc, enterprise=block_a,
        kind="income", amount_kobo=1_925_500_00, posted_at=timezone.now(),
    )
    # Money out: 1,482,500 on Block A
    Transaction.objects.create(
        tenant_id=farm.id, farm=farm, account=acc, enterprise=block_a,
        kind="expense", amount_kobo=-1_482_500_00, posted_at=timezone.now(),
    )
    resp = authed.get(reverse("pnl"))
    body = resp.json()
    assert body["money_in_kobo"] == 1_925_500_00
    assert body["money_out_kobo"] == 1_482_500_00
    assert body["net_kobo"] == 443_000_00
    assert len(body["by_enterprise"]) == 1
    ent_row = body["by_enterprise"][0]
    assert ent_row["enterprise_id"] == str(block_a.id)
    assert ent_row["net_kobo"] == 443_000_00
    assert ent_row["status"] == "projected"  # not completed yet


def test_field_staff_cannot_create_account(api_client, farm):
    field = User.objects.create_user(phone="+2348019997777")
    StaffMembership.objects.create(user=field, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=field)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(
        reverse("accounts-list"),
        {"name": "Cash", "type": "cash"},
        format="json",
    )
    assert resp.status_code == 403


def test_inventory_receipt_auto_creates_expense(authed, farm):
    """A receipt with unit_cost > 0 should drop a matching expense onto the
    farm's first cash account, linked via ref_inventory_movement."""
    from apps.inventory.models import InventoryItem, InventoryMovement, Store
    cash = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Cash", type="cash",
        opening_balance_kobo=1_000_000_00,
    )
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="NPK", category="fertilizer", unit="bags",
    )
    movement = InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op="receipt",
        qty=10, unit_cost_kobo=23_000_00,  # ₦23,000/bag
        occurred_at=timezone.now(),
    )
    tx = Transaction.objects.get(ref_inventory_movement=movement)
    assert tx.kind == "expense"
    # 10 bags × ₦23,000 = ₦230,000 (kobo: 23,000,000)
    assert tx.amount_kobo == -230_000_00
    # Account balance should drop by the expense amount.
    balance = authed.get(reverse("accounts-detail", kwargs={"pk": str(cash.id)})).json()["balance_kobo"]
    assert balance == 1_000_000_00 - 230_000_00


def test_inventory_receipt_no_double_post_on_retried_sync(authed, farm):
    """If the same receipt arrives twice via sync (retry), only one expense lands."""
    from apps.inventory.models import InventoryItem, InventoryMovement, Store
    Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash", type="cash")
    store = Store.objects.create(tenant_id=farm.id, farm=farm, name="Main")
    item = InventoryItem.objects.create(
        tenant_id=farm.id, farm=farm, name="NPK", category="fertilizer", unit="bags",
    )
    movement = InventoryMovement.objects.create(
        tenant_id=farm.id, item=item, store=store, op="receipt",
        qty=5, unit_cost_kobo=10_000_00, occurred_at=timezone.now(),
    )
    # Re-save is a no-op for our created=True guard.
    movement.save()
    assert Transaction.objects.filter(ref_inventory_movement=movement).count() == 1


def test_transaction_via_sync_push(authed, farm):
    import uuid as _uuid
    acc = Account.objects.create(
        tenant_id=farm.id, farm=farm, name="Cash", opening_balance_kobo=0,
    )
    row_id = str(_uuid.uuid4())
    resp = authed.post(
        reverse("sync-push"),
        {
            "ops": [
                {
                    "table": "finance_transaction",
                    "row_id": row_id,
                    "op": "insert",
                    "payload": {
                        "farm": str(farm.id),
                        "account": str(acc.id),
                        "kind": "income",
                        "amount_kobo": 50_000_00,
                        "description": "From offline device",
                        "posted_at": timezone.now().isoformat(),
                    },
                    "client_seq": 1,
                }
            ],
        },
        format="json",
        HTTP_X_DEVICE_ID="dev-1",
    )
    assert resp.status_code == 200, resp.content
    assert Transaction.objects.filter(pk=row_id, account=acc).exists()
