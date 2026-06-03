from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.farms.models import Farm, StaffMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(db):
    return User.objects.create_user(phone="+2348010000001", full_name="Musa")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(phone="+2348010000002")


@pytest.fixture
def authed(api_client, owner):
    api_client.force_authenticate(user=owner)
    return api_client


def _rows(resp):
    data = resp.json()
    return data["results"] if isinstance(data, dict) and "results" in data else data


def test_create_farm_attaches_owner_membership(authed, owner):
    resp = authed.post(
        reverse("farms-list"),
        {
            "name": "Musa's Farm",
            "location": {"lat": 9.671, "lng": 7.954},
            "region": "Kaduna",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.content
    farm = Farm.objects.get(name="Musa's Farm")
    assert farm.owner == owner
    membership = StaffMembership.objects.get(user=owner, farm=farm)
    assert membership.role == StaffMembership.ROLE_OWNER
    assert membership.accepted_at is not None


def test_list_farms_only_returns_user_memberships(authed, owner, other_user):
    mine = Farm.objects.create(name="Mine", owner=owner)
    Farm.objects.create(name="Theirs", owner=other_user)
    StaffMembership.objects.create(user=owner, farm=mine, role=StaffMembership.ROLE_OWNER)
    resp = authed.get(reverse("farms-list"))
    names = [r["name"] for r in _rows(resp)]
    assert "Mine" in names
    assert "Theirs" not in names


def test_invite_creates_membership_for_new_user(authed, owner):
    farm = Farm.objects.create(name="F1", owner=owner)
    StaffMembership.objects.create(user=owner, farm=farm, role=StaffMembership.ROLE_OWNER)
    resp = authed.post(
        reverse("farms-invite", kwargs={"pk": str(farm.id)}),
        {"phone": "+2348019999999", "role": "field_staff", "full_name": "Sani"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    invitee = User.objects.get(phone="+2348019999999")
    assert invitee.full_name == "Sani"
    membership = StaffMembership.objects.get(user=invitee, farm=farm)
    assert membership.role == "field_staff"
    assert membership.accepted_at is None


def test_invite_idempotent_on_repeat(authed, owner):
    farm = Farm.objects.create(name="F1", owner=owner)
    StaffMembership.objects.create(user=owner, farm=farm, role=StaffMembership.ROLE_OWNER)
    url = reverse("farms-invite", kwargs={"pk": str(farm.id)})
    first = authed.post(url, {"phone": "+2348019999999", "role": "manager"}, format="json")
    assert first.status_code == 201
    second = authed.post(url, {"phone": "+2348019999999", "role": "manager"}, format="json")
    assert second.status_code == 200
    assert StaffMembership.objects.filter(farm=farm).count() == 2  # owner + invitee


def test_field_staff_cannot_invite(api_client, owner, other_user):
    farm = Farm.objects.create(name="F1", owner=owner)
    StaffMembership.objects.create(user=owner, farm=farm, role=StaffMembership.ROLE_OWNER)
    StaffMembership.objects.create(user=other_user, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=other_user)
    resp = api_client.post(
        reverse("farms-invite", kwargs={"pk": str(farm.id)}),
        {"phone": "+2348019999999", "role": "field_staff"},
        format="json",
    )
    assert resp.status_code == 403


def test_my_memberships_endpoint(authed, owner):
    f1 = Farm.objects.create(name="F1", owner=owner)
    f2 = Farm.objects.create(name="F2", owner=owner)
    StaffMembership.objects.create(user=owner, farm=f1, role=StaffMembership.ROLE_OWNER)
    StaffMembership.objects.create(user=owner, farm=f2, role=StaffMembership.ROLE_MANAGER)
    resp = authed.get(reverse("memberships-list"))
    rows = _rows(resp)
    assert len(rows) == 2
    assert {r["role"] for r in rows} == {"owner", "manager"}

def _member(farm, user, role):
    return StaffMembership.objects.create(user=user, farm=farm, role=role)


def test_update_staff_role(authed, owner, other_user):
    farm = Farm.objects.create(name="F1", owner=owner)
    _member(farm, owner, StaffMembership.ROLE_OWNER)
    m = _member(farm, other_user, StaffMembership.ROLE_VIEWER)
    resp = authed.patch(
        reverse("farms-manage-staff", kwargs={"pk": str(farm.id), "membership_id": str(m.id)}),
        {"role": "manager"}, format="json",
    )
    assert resp.status_code == 200, resp.content
    m.refresh_from_db()
    assert m.role == "manager"


def test_update_staff_rejects_invalid_role(authed, owner, other_user):
    farm = Farm.objects.create(name="F1", owner=owner)
    _member(farm, owner, StaffMembership.ROLE_OWNER)
    m = _member(farm, other_user, StaffMembership.ROLE_VIEWER)
    resp = authed.patch(
        reverse("farms-manage-staff", kwargs={"pk": str(farm.id), "membership_id": str(m.id)}),
        {"role": "supervisor"}, format="json",
    )
    assert resp.status_code == 400


def test_remove_staff_member(authed, owner, other_user):
    farm = Farm.objects.create(name="F1", owner=owner)
    _member(farm, owner, StaffMembership.ROLE_OWNER)
    m = _member(farm, other_user, StaffMembership.ROLE_FIELD)
    resp = authed.delete(
        reverse("farms-manage-staff", kwargs={"pk": str(farm.id), "membership_id": str(m.id)}),
    )
    assert resp.status_code == 204
    assert not StaffMembership.objects.filter(pk=m.id).exists()


def test_owner_membership_is_protected(authed, owner):
    farm = Farm.objects.create(name="F1", owner=owner)
    om = _member(farm, owner, StaffMembership.ROLE_OWNER)
    patch = authed.patch(
        reverse("farms-manage-staff", kwargs={"pk": str(farm.id), "membership_id": str(om.id)}),
        {"role": "viewer"}, format="json",
    )
    assert patch.status_code == 403
    delete = authed.delete(
        reverse("farms-manage-staff", kwargs={"pk": str(farm.id), "membership_id": str(om.id)}),
    )
    assert delete.status_code == 403
    assert StaffMembership.objects.filter(pk=om.id).exists()


def test_field_staff_cannot_manage_staff(api_client, owner, other_user):
    farm = Farm.objects.create(name="F1", owner=owner)
    _member(farm, owner, StaffMembership.ROLE_OWNER)
    me = _member(farm, other_user, StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=other_user)
    resp = api_client.patch(
        reverse("farms-manage-staff", kwargs={"pk": str(farm.id), "membership_id": str(me.id)}),
        {"role": "manager"}, format="json",
    )
    assert resp.status_code == 403
