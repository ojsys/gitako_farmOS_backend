"""Sync push/pull + conflict tests using the SyncNote toy table."""
from __future__ import annotations

import uuid

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.sync.models import ChangeLog, SyncNote

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(db):
    return User.objects.create_user(phone="+2348012345678")


@pytest.fixture
def tenant_id(user):
    """Real tenant — backed by a Farm with the user as owner so the
    permission policy can resolve a role.
    """
    from apps.farms.models import Farm, StaffMembership
    farm = Farm.objects.create(name="Test Farm", owner=user)
    StaffMembership.objects.create(user=user, farm=farm, role=StaffMembership.ROLE_OWNER)
    return farm.id


@pytest.fixture
def authed_client(api_client, user, tenant_id):
    api_client.force_authenticate(user=user)
    api_client.credentials(HTTP_X_TENANT_ID=str(tenant_id), HTTP_X_DEVICE_ID="device-a")
    return api_client


def _push(client, ops):
    return client.post(reverse("sync-push"), {"ops": ops}, format="json")


def test_push_insert_creates_row_and_changelog(authed_client, tenant_id):
    row_id = str(uuid.uuid4())
    resp = _push(authed_client, [
        {
            "table": "sync_note",
            "row_id": row_id,
            "op": "insert",
            "payload": {"title": "First note", "body": "Hello"},
            "client_seq": 1,
        }
    ])
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body["accepted"]) == 1
    assert body["accepted"][0]["row_id"] == row_id
    assert body["conflicts"] == []
    assert SyncNote.objects.filter(pk=row_id).exists()
    assert ChangeLog.objects.filter(tenant_id=tenant_id, row_id=row_id, op="insert").exists()


def test_push_update_after_insert(authed_client):
    row_id = str(uuid.uuid4())
    _push(authed_client, [{"table": "sync_note", "row_id": row_id, "op": "insert",
                            "payload": {"title": "T1"}, "client_seq": 1}])
    note = SyncNote.objects.get(pk=row_id)
    base_ts = note.updated_at.isoformat()

    resp = _push(authed_client, [{
        "table": "sync_note", "row_id": row_id, "op": "update",
        "payload": {"title": "T2"}, "client_seq": 2,
        "base_updated_at": base_ts,
    }])
    assert resp.status_code == 200
    assert resp.json()["conflicts"] == []
    note.refresh_from_db()
    assert note.title == "T2"


def test_push_update_with_stale_base_returns_conflict(authed_client):
    row_id = str(uuid.uuid4())
    _push(authed_client, [{"table": "sync_note", "row_id": row_id, "op": "insert",
                            "payload": {"title": "T1"}, "client_seq": 1}])
    SyncNote.objects.filter(pk=row_id).update(updated_at=timezone.now(), title="T-server")

    resp = _push(authed_client, [{
        "table": "sync_note", "row_id": row_id, "op": "update",
        "payload": {"title": "T-client"}, "client_seq": 2,
        "base_updated_at": (timezone.now().replace(year=2000)).isoformat(),  # ancient base
    }])
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["row_id"] == row_id
    assert body["conflicts"][0]["server_payload"]["title"] == "T-server"
    assert body["conflicts"][0]["client_payload"]["title"] == "T-client"


def test_push_delete_tombstones_row(authed_client):
    row_id = str(uuid.uuid4())
    _push(authed_client, [{"table": "sync_note", "row_id": row_id, "op": "insert",
                            "payload": {"title": "T1"}, "client_seq": 1}])
    resp = _push(authed_client, [{"table": "sync_note", "row_id": row_id, "op": "delete",
                                   "payload": {}, "client_seq": 2}])
    assert resp.status_code == 200
    assert not SyncNote.objects.filter(pk=row_id).exists()
    assert SyncNote.all_objects.filter(pk=row_id, deleted_at__isnull=False).exists()


def test_pull_returns_changes_since_cursor(authed_client, tenant_id):
    row_id = str(uuid.uuid4())
    _push(authed_client, [{"table": "sync_note", "row_id": row_id, "op": "insert",
                            "payload": {"title": "T1"}, "client_seq": 1}])

    resp = authed_client.get(reverse("sync-pull"), {"since": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["changes"]) == 1
    assert body["changes"][0]["row_id"] == row_id
    assert body["changes"][0]["op"] == "insert"
    assert body["next_since"] >= 1


def test_pull_advances_with_cursor(authed_client):
    row_a, row_b = str(uuid.uuid4()), str(uuid.uuid4())
    _push(authed_client, [{"table": "sync_note", "row_id": row_a, "op": "insert",
                            "payload": {"title": "A"}, "client_seq": 1}])
    first = authed_client.get(reverse("sync-pull"), {"since": 0}).json()
    cursor = first["next_since"]

    _push(authed_client, [{"table": "sync_note", "row_id": row_b, "op": "insert",
                            "payload": {"title": "B"}, "client_seq": 2}])
    second = authed_client.get(reverse("sync-pull"), {"since": cursor}).json()
    titles = [c["payload"]["title"] for c in second["changes"]]
    assert titles == ["B"]


def test_push_requires_tenant_header(api_client, user):
    api_client.force_authenticate(user=user)
    resp = api_client.post(reverse("sync-push"), {"ops": []}, format="json")
    assert resp.status_code == 400


def test_push_unregistered_table_acknowledged_as_noop(authed_client):
    # An op for a table the server doesn't sync is acknowledged (accepted no-op)
    # so the client drops it — it must NOT 400 the batch and wedge all sync.
    row_id = str(uuid.uuid4())
    resp = _push(authed_client, [{"table": "not_real", "row_id": row_id,
                                  "op": "insert", "payload": {}, "client_seq": 1}])
    assert resp.status_code == 200, resp.content
    assert resp.json()["accepted"][0]["row_id"] == row_id


def test_idempotent_insert_with_same_client_seq(authed_client):
    row_id = str(uuid.uuid4())
    op = {"table": "sync_note", "row_id": row_id, "op": "insert",
          "payload": {"title": "T1"}, "client_seq": 1}
    _push(authed_client, [op])
    resp = _push(authed_client, [op])
    assert resp.status_code == 200
    assert SyncNote.objects.filter(pk=row_id).count() == 1


def test_push_unregistered_table_is_acknowledged_not_500(authed_client):
    """A queued op for a table the server doesn't sync (e.g. an obsolete client
    table) must be accepted as a no-op so the client drops it — never 400 the
    whole batch and wedge all syncing."""
    row_id = str(uuid.uuid4())
    resp = _push(authed_client, [
        {"table": "farms_party", "row_id": row_id, "op": "insert",
         "payload": {"name": "Dr. Tunde"}, "client_seq": 1},
    ])
    assert resp.status_code == 200, resp.content
    assert resp.json()["accepted"][0]["row_id"] == row_id


def test_push_unknown_table_does_not_block_good_ops(authed_client):
    """A bad op alongside a good one shouldn't roll back the good one."""
    bad = str(uuid.uuid4())
    good = str(uuid.uuid4())
    resp = _push(authed_client, [
        {"table": "farms_party", "row_id": bad, "op": "insert",
         "payload": {}, "client_seq": 1},
        {"table": "sync_note", "row_id": good, "op": "insert",
         "payload": {"title": "ok"}, "client_seq": 1},
    ])
    assert resp.status_code == 200, resp.content
    accepted = {a["row_id"] for a in resp.json()["accepted"]}
    assert bad in accepted and good in accepted
    assert SyncNote.objects.filter(pk=good).exists()
