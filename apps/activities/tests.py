from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
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
def enterprise(farm):
    return Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="crop_cycle",
        name="Block A · Maize", attrs={"crop": "maize", "area_ha": 5},
    )


@pytest.fixture
def authed(api_client, owner, farm):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    return api_client


def test_create_activity(authed, enterprise):
    resp = authed.post(
        reverse("activities-list"),
        {
            "enterprise": str(enterprise.id),
            "type": "planting",
            "occurred_at": timezone.now().isoformat(),
            "cost_kobo": 250000,
            "notes": "Planted block A",
            "gps_point": {"lat": 9.67, "lng": 7.95},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    act = Activity.objects.get(id=resp.json()["id"])
    assert act.type == "planting"
    assert act.actor_user_id  # auto-set to caller
    assert act.tenant_id == enterprise.tenant_id


def test_field_staff_can_create_but_approval_pending(authed, enterprise, farm):
    field = User.objects.create_user(phone="+2348019999001")
    StaffMembership.objects.create(user=field, farm=farm, role=StaffMembership.ROLE_FIELD)

    from rest_framework.test import APIClient
    fc = APIClient()
    fc.force_authenticate(user=field)
    fc.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = fc.post(
        reverse("activities-list"),
        {"enterprise": str(enterprise.id), "type": "feed", "occurred_at": timezone.now().isoformat()},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["approved_at"] is None


def test_only_owner_can_approve(api_client, owner, farm, enterprise):
    field = User.objects.create_user(phone="+2348019999002")
    StaffMembership.objects.create(user=field, farm=farm, role=StaffMembership.ROLE_FIELD)
    activity = Activity.objects.create(
        enterprise=enterprise, tenant_id=enterprise.tenant_id,
        type="feed", occurred_at=timezone.now(), actor_user=field,
    )

    api_client.force_authenticate(user=field)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    bad = api_client.post(reverse("activities-approve", kwargs={"pk": str(activity.id)}))
    assert bad.status_code == 403

    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    good = api_client.post(reverse("activities-approve", kwargs={"pk": str(activity.id)}))
    assert good.status_code == 200
    activity.refresh_from_db()
    assert activity.approved_at is not None
    assert activity.approved_by == owner


def test_list_filters_by_enterprise(authed, enterprise, farm):
    other_ent = Enterprise.objects.create(
        farm=farm, tenant_id=farm.id, type="flock",
        name="Pen 1", attrs={"kind": "broiler", "bird_count": 100},
    )
    Activity.objects.create(enterprise=enterprise, tenant_id=enterprise.tenant_id,
                            type="planting", occurred_at=timezone.now())
    Activity.objects.create(enterprise=other_ent, tenant_id=other_ent.tenant_id,
                            type="feed", occurred_at=timezone.now())

    resp = authed.get(reverse("activities-list"), {"enterprise": str(enterprise.id)})
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    assert len(rows) == 1
    assert rows[0]["type"] == "planting"


def test_media_upload_returns_dev_url(authed):
    """In dev (no S3 creds), the endpoint returns a backend-hosted upload URL."""
    resp = authed.post(
        reverse("media-upload-url"),
        {"ext": "jpg", "purpose": "activity_photo"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["key"].startswith("activity_photo/")
    assert body["key"].endswith(".jpg")
    assert "/api/media/dev-upload/" in body["upload_url"]
    assert body["method"] == "PUT"
    assert body["headers"]["Content-Type"] == "image/jpeg"


def test_media_upload_rejects_unknown_extension(authed):
    resp = authed.post(
        reverse("media-upload-url"),
        {"ext": "exe"},
        format="json",
    )
    assert resp.status_code == 400


def test_dev_upload_sink_writes_file(authed, tmp_path, settings):
    settings.BASE_DIR = tmp_path
    # Get an upload URL first
    presign = authed.post(
        reverse("media-upload-url"),
        {"ext": "png"},
        format="json",
    ).json()
    key = presign["key"]
    # PUT bytes to the dev sink
    resp = authed.put(
        reverse("media-dev-upload", kwargs={"key": key}),
        b"fake-png-bytes",
        content_type="image/png",
    )
    assert resp.status_code == 200
    written = tmp_path / "media" / key
    assert written.exists()
    assert written.read_bytes() == b"fake-png-bytes"


def test_field_staff_can_only_edit_own_activity(api_client, farm, enterprise, owner):
    field = User.objects.create_user(phone="+2348019998877")
    StaffMembership.objects.create(user=field, farm=farm, role=StaffMembership.ROLE_FIELD)
    owner_act = Activity.objects.create(
        enterprise=enterprise, tenant_id=enterprise.tenant_id,
        type="feed", occurred_at=timezone.now(), actor_user=owner,
    )
    own_act = Activity.objects.create(
        enterprise=enterprise, tenant_id=enterprise.tenant_id,
        type="feed", occurred_at=timezone.now(), actor_user=field,
    )
    api_client.force_authenticate(user=field)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))

    own_resp = api_client.patch(
        reverse("activities-detail", kwargs={"pk": str(own_act.id)}),
        {"notes": "tweaked"}, format="json",
    )
    assert own_resp.status_code == 200, own_resp.content
    other_resp = api_client.patch(
        reverse("activities-detail", kwargs={"pk": str(owner_act.id)}),
        {"notes": "should fail"}, format="json",
    )
    assert other_resp.status_code == 403


def test_viewer_cannot_create_activity(api_client, farm, enterprise):
    viewer = User.objects.create_user(phone="+2348019998866")
    StaffMembership.objects.create(user=viewer, farm=farm, role=StaffMembership.ROLE_VIEWER)
    api_client.force_authenticate(user=viewer)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(
        reverse("activities-list"),
        {"enterprise": str(enterprise.id), "type": "feed",
         "occurred_at": timezone.now().isoformat()},
        format="json",
    )
    assert resp.status_code == 403


def test_sync_push_rejects_field_staff_editing_others(api_client, farm, enterprise, owner):
    """Permission policy must hold via the offline sync path too."""
    import uuid as _uuid
    field = User.objects.create_user(phone="+2348019998855")
    StaffMembership.objects.create(user=field, farm=farm, role=StaffMembership.ROLE_FIELD)
    owner_act = Activity.objects.create(
        enterprise=enterprise, tenant_id=enterprise.tenant_id,
        type="feed", occurred_at=timezone.now(), actor_user=owner,
    )
    api_client.force_authenticate(user=field)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id), HTTP_X_DEVICE_ID="dev-1")
    resp = api_client.post(
        reverse("sync-push"),
        {
            "ops": [
                {
                    "table": "activities_activity",
                    "row_id": str(owner_act.id),
                    "op": "update",
                    "payload": {"notes": "should fail"},
                    "client_seq": 99,
                }
            ],
        },
        format="json",
    )
    assert resp.status_code == 403, resp.content
    assert _uuid.UUID(str(owner_act.id))  # row exists
    owner_act.refresh_from_db()
    assert owner_act.notes != 'should fail'


def test_activity_pushes_via_sync(authed, enterprise, farm):
    """Confirm Activity is sync-registered: a push lands the row server-side."""
    import uuid
    row_id = str(uuid.uuid4())
    resp = authed.post(
        reverse("sync-push"),
        {
            "ops": [
                {
                    "table": "activities_activity",
                    "row_id": row_id,
                    "op": "insert",
                    "payload": {
                        "enterprise": str(enterprise.id),
                        "type": "weeding",
                        "occurred_at": timezone.now().isoformat(),
                        "notes": "from offline device",
                    },
                    "client_seq": 1,
                }
            ],
        },
        format="json",
        HTTP_X_DEVICE_ID="dev-1",
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert len(body["accepted"]) == 1
    assert Activity.objects.filter(pk=row_id, type="weeding").exists()
