"""M16 Farm Credit Score — composite scoring, breakdown, consent-gated partner read."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.creditscore.engine import compute_score
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.finance.models import Account, Transaction
from apps.partners import models as pm
from apps.partners.auth import generate_api_key

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return User.objects.create_user(phone="+2348010000001")


@pytest.fixture
def farm(owner):
    f = Farm.objects.create(name="Lekan Farms", owner=owner)
    StaffMembership.objects.create(user=owner, farm=f, role=StaffMembership.ROLE_OWNER)
    return f


@pytest.fixture
def authed(api_client, owner, farm):
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    return api_client


def _build_track_record(farm):
    ent = Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type="crop_cycle", name="Block A",
        lifecycle_state="active", attrs={"crop": "maize", "area_ha": 2},
    )
    now = timezone.now()
    # spread activities across recent weeks for consistency
    for wk in range(6):
        for _ in range(7):
            Activity.objects.create(tenant_id=farm.id, enterprise=ent, type="weeding",
                                    occurred_at=now - timezone.timedelta(weeks=wk, hours=1))
    acc = Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash", type="cash")
    Transaction.objects.create(tenant_id=farm.id, farm=farm, account=acc, kind="income",
                               amount_kobo=900_000_00, posted_at=now)
    Transaction.objects.create(tenant_id=farm.id, farm=farm, account=acc, kind="expense",
                               amount_kobo=-300_000_00, posted_at=now)
    return ent


def test_empty_farm_scores_low_but_in_range(farm):
    result = compute_score(farm)
    assert 300 <= result["score"] <= 850
    assert result["band"] == "building"
    assert set(result["components"]) == {
        "record_completeness", "activity_consistency",
        "financial_performance", "repayment_history",
    }


def test_track_record_raises_score(farm):
    empty = compute_score(farm)["score"]
    _build_track_record(farm)
    full = compute_score(farm)["score"]
    assert full > empty
    assert full >= 580  # at least "fair"


def test_no_loan_history_is_neutral_not_zero(farm):
    comp = compute_score(farm)["components"]["repayment_history"]
    assert comp["score"] == 60.0


def test_my_score_endpoint(authed, farm):
    _build_track_record(farm)
    resp = authed.get(reverse("credit-score"))
    assert resp.status_code == 200
    body = resp.json()
    assert "score" in body and "components" in body
    assert body["max_score"] == 850


def test_my_score_requires_membership(api_client, farm):
    stranger = User.objects.create_user(phone="+2348010000099")
    api_client.force_authenticate(user=stranger)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.get(reverse("credit-score"))
    assert resp.status_code == 403


# ---------- partner read via M14 consent ----------

def test_partner_credit_score_requires_consent(api_client, farm):
    partner = pm.Partner.objects.create(name="Sterling MFI", kind="bank")
    raw, prefix, key_hash = generate_api_key()
    pm.ApiKey.objects.create(partner=partner, prefix=prefix, key_hash=key_hash)
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    resp = api_client.get(reverse("partner-credit-score", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 403


def test_partner_credit_score_with_consent(api_client, farm):
    partner = pm.Partner.objects.create(name="Sterling MFI", kind="bank")
    raw, prefix, key_hash = generate_api_key()
    pm.ApiKey.objects.create(partner=partner, prefix=prefix, key_hash=key_hash)
    pm.ConsentGrant.objects.create(partner=partner, farm=farm,
                                   scopes=[pm.SCOPE_CREDIT], is_active=True)
    _build_track_record(farm)
    api_client.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    resp = api_client.get(reverse("partner-credit-score", kwargs={"farm_id": str(farm.id)}))
    assert resp.status_code == 200
    body = resp.json()
    assert "score" in body and "band" in body
    # Partners get headline only — not the component breakdown.
    assert "components" not in body
