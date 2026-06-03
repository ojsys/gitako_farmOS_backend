"""M15 Extension officer / vet — consent boundary, advisories, visits, report."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.enterprises.models import Enterprise
from apps.extension.models import Advisory, OfficerAccess, Visit
from apps.farms.models import Farm, StaffMembership
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(phone="+2348010000001", full_name="Lekan")


@pytest.fixture
def farm(owner):
    f = Farm.objects.create(name="Lekan Farms", owner=owner)
    StaffMembership.objects.create(user=owner, farm=f, role=StaffMembership.ROLE_OWNER)
    return f


@pytest.fixture
def officer():
    return User.objects.create_user(phone="+2348019999000", full_name="Officer Musa")


@pytest.fixture
def officer_client(api_client, officer):
    api_client.force_authenticate(user=officer)
    return api_client


@pytest.fixture
def owner_client(api_client, owner, farm):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    return api_client


def _grant_active(officer, farm):
    return OfficerAccess.objects.create(officer=officer, farm=farm,
                                        status=OfficerAccess.STATUS_ACTIVE,
                                        approved_at=timezone.now())


# ---------- access request + approval ----------

def test_officer_requests_access_notifies_owner(officer_client, officer, farm, owner):
    resp = officer_client.post(reverse("officer-request-access"),
                               {"farm_id": str(farm.id), "program": "Oyo ADP"}, format="json")
    assert resp.status_code == 201
    access = OfficerAccess.objects.get(officer=officer, farm=farm)
    assert access.status == "pending"
    assert Notification.objects.filter(user=owner, title__icontains="access").exists()


def test_owner_approves_access(owner_client, officer, farm):
    access = OfficerAccess.objects.create(officer=officer, farm=farm, status="pending")
    resp = owner_client.post(reverse("farm-officer-access"),
                             {"officer_access_id": str(access.id), "action": "approve"}, format="json")
    assert resp.status_code == 200
    access.refresh_from_db()
    assert access.status == "active"


def test_owner_revokes_access(owner_client, officer, farm):
    access = _grant_active(officer, farm)
    resp = owner_client.post(reverse("farm-officer-access"),
                             {"officer_access_id": str(access.id), "action": "revoke"}, format="json")
    assert resp.status_code == 200
    access.refresh_from_db()
    assert access.status == "revoked"


def test_field_staff_cannot_manage_access(api_client, farm, officer):
    staff = User.objects.create_user(phone="+2348010000077")
    StaffMembership.objects.create(user=staff, farm=farm, role=StaffMembership.ROLE_FIELD)
    access = OfficerAccess.objects.create(officer=officer, farm=farm, status="pending")
    api_client.force_authenticate(user=staff)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("farm-officer-access"),
                           {"officer_access_id": str(access.id), "action": "approve"}, format="json")
    assert resp.status_code == 403


# ---------- advisories (consent boundary) ----------

def test_advisory_denied_without_active_access(officer_client, farm):
    resp = officer_client.post(reverse("officer-advisory"),
                               {"farm_id": str(farm.id), "title": "Spray now"}, format="json")
    assert resp.status_code == 403


def test_advisory_issued_with_access_notifies_farm(officer_client, officer, farm, owner):
    _grant_active(officer, farm)
    resp = officer_client.post(reverse("officer-advisory"),
                               {"farm_id": str(farm.id), "title": "Vaccinate Batch 17",
                                "body": "Newcastle due", "severity": "urgent"}, format="json")
    assert resp.status_code == 201, resp.content
    assert Advisory.objects.filter(farm=farm, title="Vaccinate Batch 17").exists()
    assert Notification.objects.filter(user=owner, title__icontains="Vaccinate Batch 17").exists()


def test_roster_lists_only_active_farms(officer_client, officer, farm):
    other_owner = User.objects.create_user(phone="+2348010000222")
    other = Farm.objects.create(name="Other", owner=other_owner)
    _grant_active(officer, farm)
    OfficerAccess.objects.create(officer=officer, farm=other, status="pending")
    resp = officer_client.get(reverse("officer-roster"))
    farm_ids = {f["farm"] for f in resp.json()["farms"]}
    assert str(farm.id) in farm_ids
    assert str(other.id) not in farm_ids


# ---------- visits ----------

def test_officer_schedules_visit(officer_client, officer, farm):
    _grant_active(officer, farm)
    resp = officer_client.post(reverse("officer-visits-list"),
                               {"farm": str(farm.id), "scheduled_for": "2026-07-01",
                                "purpose": "Disease check"}, format="json")
    assert resp.status_code == 201, resp.content
    assert Visit.objects.filter(officer=officer, farm=farm).exists()


def test_visit_denied_without_access(officer_client, farm):
    resp = officer_client.post(reverse("officer-visits-list"),
                               {"farm": str(farm.id), "scheduled_for": "2026-07-01"}, format="json")
    assert resp.status_code == 403


# ---------- aggregate report ----------

def test_officer_aggregate_report(officer_client, officer, farm):
    _grant_active(officer, farm)
    Enterprise.objects.create(tenant_id=farm.id, farm=farm, type="crop_cycle", name="A",
                              lifecycle_state="active", attrs={"crop": "maize", "area_ha": 1})
    resp = officer_client.get(reverse("officer-report"))
    body = resp.json()
    assert body["farm_count"] == 1
    assert body["enterprise_count"] == 1


# ---------- farmer reads advisories ----------

def test_farm_advisories_readable_by_member(owner_client, officer, farm):
    _grant_active(officer, farm)
    Advisory.objects.create(officer=officer, farm=farm, title="Note", severity="info")
    resp = owner_client.get(reverse("farm-advisories"))
    assert resp.status_code == 200
    assert len(resp.json()["advisories"]) == 1


def test_farm_advisories_blocked_for_non_member(api_client, farm):
    stranger = User.objects.create_user(phone="+2348010000333")
    api_client.force_authenticate(user=stranger)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.get(reverse("farm-advisories"))
    assert resp.status_code == 403
