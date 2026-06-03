"""M14 Partner API — API-key auth, consent gating, scope enforcement, audit."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.partners import models as m
from apps.partners.auth import generate_api_key

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(phone="+2348010000001")


@pytest.fixture
def farm(owner):
    f = Farm.objects.create(name="Lekan Farms", owner=owner, region="Oyo")
    StaffMembership.objects.create(user=owner, farm=f, role=StaffMembership.ROLE_OWNER)
    return f


@pytest.fixture
def partner():
    return m.Partner.objects.create(name="Sterling MFI", kind="bank")


@pytest.fixture
def raw_key(partner):
    raw, prefix, key_hash = generate_api_key()
    m.ApiKey.objects.create(partner=partner, prefix=prefix, key_hash=key_hash)
    return raw


@pytest.fixture
def key_client(api_client, raw_key):
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw_key}")
    return api_client


def _grant(partner, farm, scopes):
    return m.ConsentGrant.objects.create(partner=partner, farm=farm, scopes=scopes, is_active=True)


# ---------- auth ----------

def test_missing_key_rejected(api_client, farm):
    resp = api_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code in (401, 403)


def test_bad_key_rejected(api_client, farm):
    api_client.credentials(HTTP_AUTHORIZATION="Api-Key gk_totallybogus")
    resp = api_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 401


# ---------- consent gating ----------

def test_registry_denied_without_consent(key_client, farm):
    resp = key_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 403


def test_registry_allowed_with_consent(key_client, partner, farm):
    _grant(partner, farm, [m.SCOPE_REGISTRY])
    resp = key_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Lekan Farms"


def test_scope_is_enforced(key_client, partner, farm):
    # Granted registry only — aggregate must still be denied.
    _grant(partner, farm, [m.SCOPE_REGISTRY])
    resp = key_client.get(reverse("partner-aggregate", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 403


def test_aggregate_returns_rollups(key_client, partner, farm):
    _grant(partner, farm, [m.SCOPE_AGGREGATE])
    Enterprise.objects.create(tenant_id=farm.id, farm=farm, type="crop_cycle", name="A",
                              lifecycle_state="active", attrs={"crop": "maize", "area_ha": 1})
    resp = key_client.get(reverse("partner-aggregate", kwargs={"farm_id": str(farm.id)}))
    body = resp.json()
    assert body["enterprise_count"] == 1
    assert "net_kobo" in body


def test_activity_events_omit_sensitive_fields(key_client, partner, farm):
    _grant(partner, farm, [m.SCOPE_ACTIVITY])
    ent = Enterprise.objects.create(tenant_id=farm.id, farm=farm, type="crop_cycle", name="A",
                                    lifecycle_state="active", attrs={"crop": "maize", "area_ha": 1})
    Activity.objects.create(tenant_id=farm.id, enterprise=ent, type="planting",
                            occurred_at=timezone.now(), notes="secret note", cost_kobo=999)
    resp = key_client.get(reverse("partner-activity", kwargs={"farm_id": str(farm.id)}))
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "planting"
    assert "notes" not in events[0]
    assert "cost_kobo" not in events[0]


def test_revoked_consent_blocks_access(key_client, partner, farm):
    grant = _grant(partner, farm, [m.SCOPE_REGISTRY])
    grant.is_active = False
    grant.save()
    resp = key_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 403


def test_consents_listing(key_client, partner, farm):
    _grant(partner, farm, [m.SCOPE_REGISTRY])
    resp = key_client.get(reverse("partner-consents"))
    assert resp.status_code == 200
    assert str(farm.id) in {f["farm_id"] for f in resp.json()["farms"]}


# ---------- audit ----------

def test_access_is_audited(key_client, partner, farm):
    _grant(partner, farm, [m.SCOPE_REGISTRY])
    key_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert m.PartnerAuditEntry.objects.filter(partner=partner, scope=m.SCOPE_REGISTRY,
                                              status_code=200).exists()


def test_denied_access_is_audited(key_client, partner, farm):
    key_client.get(reverse("partner-registry", kwargs={"farm_id": str(farm.id)}))
    assert m.PartnerAuditEntry.objects.filter(partner=partner, status_code=403).exists()


# ---------- farmer-facing consent control ----------

def test_owner_grants_and_revokes_consent(api_client, owner, farm, partner):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    grant = api_client.post(reverse("farm-consent"),
                            {"partner_id": str(partner.id), "scopes": ["registry", "aggregate"]},
                            format="json")
    assert grant.status_code == 200
    assert m.ConsentGrant.objects.get(partner=partner, farm=farm).is_active

    revoke = api_client.delete(reverse("farm-consent"), {"partner_id": str(partner.id)}, format="json")
    assert revoke.status_code == 204
    assert not m.ConsentGrant.objects.get(partner=partner, farm=farm).is_active


def test_consent_rejects_unknown_scope(api_client, owner, farm, partner):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("farm-consent"),
                           {"partner_id": str(partner.id), "scopes": ["everything"]},
                           format="json")
    assert resp.status_code == 400


def test_field_staff_cannot_manage_consent(api_client, farm, partner):
    staff = User.objects.create_user(phone="+2348010000077")
    StaffMembership.objects.create(user=staff, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=staff)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("farm-consent"),
                           {"partner_id": str(partner.id), "scopes": ["registry"]}, format="json")
    assert resp.status_code == 403
