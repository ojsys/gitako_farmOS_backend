"""M18 Embedded Finance — loan lifecycle, credit snapshot, disbursement, insurance, inputs."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.farms.models import Farm, StaffMembership
from apps.finance_partners.models import InputFinancing, InsuranceQuote, LoanApplication
from apps.partners.models import Partner

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


@pytest.fixture
def partner():
    return Partner.objects.create(name="Sterling MFI", kind="bank")


# ---------- loan lifecycle ----------

def test_apply_then_submit_snapshots_score(authed, farm, partner):
    apply = authed.post(reverse("loans-list"),
                        {"amount_kobo": 50_000_000, "purpose": "inputs", "term_days": 180},
                        format="json")
    assert apply.status_code == 201, apply.content
    loan_id = apply.json()["id"]
    assert apply.json()["status"] == "draft"

    submit = authed.post(reverse("loans-submit", kwargs={"pk": loan_id}),
                         {"partner_id": str(partner.id)}, format="json")
    assert submit.status_code == 200, submit.content
    body = submit.json()
    assert body["status"] == "submitted"
    assert body["credit_score_snapshot"] is not None
    assert 300 <= body["credit_score_snapshot"] <= 850


def test_full_loan_lifecycle_to_repaid(authed, farm, partner):
    loan_id = authed.post(reverse("loans-list"),
                          {"amount_kobo": 30_000_000, "purpose": "feed"}, format="json").json()["id"]
    authed.post(reverse("loans-submit", kwargs={"pk": loan_id}),
                {"partner_id": str(partner.id)}, format="json")
    offer = authed.post(reverse("loans-offer", kwargs={"pk": loan_id}),
                        {"terms": {"interest_pct": 12}}, format="json")
    assert offer.json()["status"] == "offered"
    assert authed.post(reverse("loans-accept", kwargs={"pk": loan_id})).json()["status"] == "accepted"
    disbursed = authed.post(reverse("loans-disburse", kwargs={"pk": loan_id}))
    assert disbursed.json()["status"] == "disbursed"
    assert disbursed.json()["disbursement_reference"] != ""
    assert authed.post(reverse("loans-repay", kwargs={"pk": loan_id})).json()["status"] == "repaid"


def test_cannot_disburse_before_accept(authed, farm):
    loan_id = authed.post(reverse("loans-list"),
                          {"amount_kobo": 1_000_000}, format="json").json()["id"]
    resp = authed.post(reverse("loans-disburse", kwargs={"pk": loan_id}))
    assert resp.status_code == 400


def test_loan_apply_requires_manager(api_client, farm):
    staff = User.objects.create_user(phone="+2348010000077")
    StaffMembership.objects.create(user=staff, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=staff)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("loans-list"), {"amount_kobo": 1_000_000}, format="json")
    assert resp.status_code == 403


def test_loans_are_farm_scoped(api_client, owner, farm):
    other_owner = User.objects.create_user(phone="+2348010000222")
    other = Farm.objects.create(name="Other", owner=other_owner)
    StaffMembership.objects.create(user=other_owner, farm=other, role=StaffMembership.ROLE_OWNER)
    LoanApplication.objects.create(farm=other, amount_kobo=1, applicant=other_owner)

    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.get(reverse("loans-list"))
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    assert rows == []


def test_repayment_history_feeds_credit_score(authed, farm, partner):
    """A repaid on-platform loan should lift the repayment_history component above neutral."""
    from apps.creditscore.engine import compute_score
    baseline = compute_score(farm)["components"]["repayment_history"]["score"]
    assert baseline == 60.0
    loan = LoanApplication.objects.create(farm=farm, amount_kobo=1, applicant=farm.owner,
                                          status=LoanApplication.STATUS_REPAID)
    after = compute_score(farm)["components"]["repayment_history"]
    assert after["score"] > baseline
    assert after["factors"]["repaid"] == 1


# ---------- insurance ----------

def test_insurance_request_quote_bind(authed, farm, partner):
    req = authed.post(reverse("insurance-list"),
                      {"kind": "weather_index", "coverage_kobo": 100_000_000,
                       "partner": str(partner.id)}, format="json")
    assert req.status_code == 201, req.content
    qid = req.json()["id"]
    quoted = authed.post(reverse("insurance-quote", kwargs={"pk": qid}),
                         {"premium_kobo": 5_000_000}, format="json")
    assert quoted.json()["status"] == "quoted"
    assert quoted.json()["premium_kobo"] == 5_000_000
    bound = authed.post(reverse("insurance-bind", kwargs={"pk": qid}))
    assert bound.json()["status"] == "bound"


# ---------- input financing ----------

def test_input_financing_request_approve(authed, farm, partner):
    req = authed.post(reverse("input-financing-list"),
                      {"description": "10 bags NPK", "value_kobo": 8_000_000,
                       "repay_after_days": 120, "partner": str(partner.id)}, format="json")
    assert req.status_code == 201, req.content
    fid = req.json()["id"]
    approved = authed.post(reverse("input-financing-approve", kwargs={"pk": fid}))
    assert approved.json()["status"] == "approved"
