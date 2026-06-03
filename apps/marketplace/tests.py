"""M13 Marketplace — cross-tenant browse, farm-scoped writes, verified badge."""
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.finance.models import Account, Transaction
from apps.marketplace.models import Listing

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


def test_create_listing_requires_manager(api_client, farm):
    viewer = User.objects.create_user(phone="+2348010000055")
    StaffMembership.objects.create(user=viewer, farm=farm, role=StaffMembership.ROLE_VIEWER)
    api_client.force_authenticate(user=viewer)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("my-listings-list"),
                           {"title": "Maize 50 bags", "kind": "produce", "price_kobo": 5_000_000},
                           format="json")
    assert resp.status_code == 403


def test_owner_creates_listing(authed, farm):
    resp = authed.post(reverse("my-listings-list"),
                       {"title": "Maize 50 bags", "kind": "produce", "price_kobo": 5_000_000,
                        "unit": "bags", "region": "Oyo"},
                       format="json")
    assert resp.status_code == 201, resp.content
    assert Listing.objects.filter(farm=farm, title="Maize 50 bags").exists()


def test_browse_is_cross_tenant(api_client):
    # Two farms, each with a listing; a user from farm A sees farm B's listing.
    ua = User.objects.create_user(phone="+2348010000010")
    fa = Farm.objects.create(name="Farm A", owner=ua)
    StaffMembership.objects.create(user=ua, farm=fa, role=StaffMembership.ROLE_OWNER)
    ub = User.objects.create_user(phone="+2348010000011")
    fb = Farm.objects.create(name="Farm B", owner=ub)
    Listing.objects.create(farm=fb, title="Goats", kind="livestock", price_kobo=8_000_000)

    api_client.force_authenticate(user=ua)
    api_client.credentials(HTTP_X_TENANT_ID=str(fa.id))
    resp = api_client.get(reverse("listings-list"))
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    titles = {r["title"] for r in rows}
    assert "Goats" in titles


def test_browse_filters_by_kind(authed, farm):
    Listing.objects.create(farm=farm, title="Maize", kind="produce", price_kobo=1)
    Listing.objects.create(farm=farm, title="Cattle", kind="livestock", price_kobo=1)
    resp = authed.get(reverse("listings-list"), {"kind": "livestock"})
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    assert all(r["kind"] == "livestock" for r in rows)


def test_withdrawn_listing_not_browsable(authed, farm):
    listing = Listing.objects.create(farm=farm, title="Old", kind="produce",
                                     price_kobo=1, status="withdrawn")
    resp = authed.get(reverse("listings-list"))
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    assert str(listing.id) not in {r["id"] for r in rows}


def test_delete_withdraws_listing(authed, farm):
    listing = Listing.objects.create(farm=farm, title="Yam", kind="produce", price_kobo=1)
    resp = authed.delete(reverse("my-listings-detail", kwargs={"pk": str(listing.id)}))
    assert resp.status_code == 204
    listing.refresh_from_db()
    assert listing.status == "withdrawn"


def test_contact_reveals_seller(authed, farm):
    listing = Listing.objects.create(farm=farm, title="Eggs", kind="produce",
                                     price_kobo=1, contact_phone="+2348011112222")
    resp = authed.get(reverse("listings-contact", kwargs={"pk": str(listing.id)}))
    assert resp.json()["contact_phone"] == "+2348011112222"


def test_verified_badge_false_without_records(authed, farm):
    Listing.objects.create(farm=farm, title="Plain", kind="produce", price_kobo=1)
    resp = authed.get(reverse("listings-list"))
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    assert all(r["verified_seller"] is False for r in rows)


def test_verified_badge_true_with_consistent_records(authed, farm):
    ent = Enterprise.objects.create(
        tenant_id=farm.id, farm=farm, type="crop_cycle", name="Block A",
        lifecycle_state="active", attrs={"crop": "maize", "area_ha": 2},
    )
    for _ in range(10):
        Activity.objects.create(tenant_id=farm.id, enterprise=ent, type="weeding",
                                occurred_at=timezone.now())
    acc = Account.objects.create(tenant_id=farm.id, farm=farm, name="Cash", type="cash")
    Transaction.objects.create(tenant_id=farm.id, farm=farm, account=acc, kind="income",
                               amount_kobo=100, posted_at=timezone.now())
    Listing.objects.create(farm=farm, title="Verified maize", kind="produce", price_kobo=1)
    resp = authed.get(reverse("listings-list"))
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    match = [r for r in rows if r["title"] == "Verified maize"][0]
    assert match["verified_seller"] is True


# ---------- M17 Marketplace v2 / escrow ----------

@pytest.fixture
def buyer():
    return User.objects.create_user(phone="+2348012223333")


@pytest.fixture
def listing(farm):
    return Listing.objects.create(farm=farm, title="Maize 50 bags", kind="produce",
                                  price_kobo=5_000_000, status="active")


def _buyer_client(api_client, buyer):
    api_client.force_authenticate(user=buyer)
    return api_client


def test_buyer_makes_offer(api_client, buyer, listing):
    from django.urls import reverse
    c = _buyer_client(api_client, buyer)
    resp = c.post(reverse("offers-list"),
                  {"listing": str(listing.id), "offer_price_kobo": 4_500_000}, format="json")
    assert resp.status_code == 201, resp.content
    from apps.marketplace.models import Offer
    assert Offer.objects.filter(buyer=buyer, listing=listing).exists()


def test_seller_cannot_offer_on_own_listing(authed, owner, listing):
    from django.urls import reverse
    resp = authed.post(reverse("offers-list"),
                       {"listing": str(listing.id), "offer_price_kobo": 1}, format="json")
    assert resp.status_code == 400


def test_full_escrow_happy_path(api_client, owner, buyer, farm, listing):
    from django.urls import reverse
    from apps.marketplace.models import Contract

    # buyer offers
    bc = _buyer_client(api_client, buyer)
    offer = bc.post(reverse("offers-list"),
                    {"listing": str(listing.id), "offer_price_kobo": 4_500_000}, format="json").json()

    # seller accepts → contract in 'agreed'
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    accept = api_client.post(reverse("offers-accept", kwargs={"pk": offer["id"]}))
    assert accept.status_code == 201, accept.content
    cid = accept.json()["id"]
    assert accept.json()["state"] == "agreed"

    # buyer funds → 'funded'
    bc = _buyer_client(api_client, buyer)
    bc.credentials()  # clear tenant header
    funded = bc.post(reverse("contracts-fund", kwargs={"pk": cid}))
    assert funded.status_code == 200, funded.content
    assert funded.json()["state"] == "funded"

    # seller delivers → 'delivered'
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    delivered = api_client.post(reverse("contracts-deliver", kwargs={"pk": cid}))
    assert delivered.json()["state"] == "delivered"

    # buyer QA pass
    bc = _buyer_client(api_client, buyer)
    bc.credentials()
    qa = bc.post(reverse("contracts-qa", kwargs={"pk": cid}), {"passed": True}, format="json")
    assert qa.json()["qa_result"] == "passed"

    # buyer releases → 'released', listing sold
    released = bc.post(reverse("contracts-release", kwargs={"pk": cid}))
    assert released.json()["state"] == "released"
    listing.refresh_from_db()
    assert listing.status == "sold"
    assert Contract.objects.get(pk=cid).release_reference != ""


def test_cannot_release_before_delivery(api_client, owner, buyer, farm, listing):
    from django.urls import reverse
    bc = _buyer_client(api_client, buyer)
    offer = bc.post(reverse("offers-list"),
                    {"listing": str(listing.id), "offer_price_kobo": 1_000_000}, format="json").json()
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    cid = api_client.post(reverse("offers-accept", kwargs={"pk": offer["id"]})).json()["id"]
    bc = _buyer_client(api_client, buyer)
    bc.credentials()
    bc.post(reverse("contracts-fund", kwargs={"pk": cid}))
    # release straight after funding (no delivery) → 400
    resp = bc.post(reverse("contracts-release", kwargs={"pk": cid}))
    assert resp.status_code == 400


def test_qa_fail_disputes_and_blocks_release(api_client, owner, buyer, farm, listing):
    from django.urls import reverse
    bc = _buyer_client(api_client, buyer)
    offer = bc.post(reverse("offers-list"),
                    {"listing": str(listing.id), "offer_price_kobo": 1_000_000}, format="json").json()
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    cid = api_client.post(reverse("offers-accept", kwargs={"pk": offer["id"]})).json()["id"]
    bc = _buyer_client(api_client, buyer)
    bc.credentials()
    bc.post(reverse("contracts-fund", kwargs={"pk": cid}))
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    api_client.post(reverse("contracts-deliver", kwargs={"pk": cid}))
    bc = _buyer_client(api_client, buyer)
    bc.credentials()
    qa = bc.post(reverse("contracts-qa", kwargs={"pk": cid}), {"passed": False, "notes": "moldy"},
                 format="json")
    assert qa.json()["state"] == "disputed"
    # release blocked while disputed via the delivered path
    refund = bc.post(reverse("contracts-refund", kwargs={"pk": cid}))
    assert refund.json()["state"] == "refunded"


def test_non_party_cannot_see_contract(api_client, owner, buyer, farm, listing):
    from django.urls import reverse
    bc = _buyer_client(api_client, buyer)
    offer = bc.post(reverse("offers-list"),
                    {"listing": str(listing.id), "offer_price_kobo": 1}, format="json").json()
    api_client.force_authenticate(user=owner)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    cid = api_client.post(reverse("offers-accept", kwargs={"pk": offer["id"]})).json()["id"]
    stranger = User.objects.create_user(phone="+2348019998888")
    api_client.force_authenticate(user=stranger)
    api_client.credentials()
    resp = api_client.get(reverse("contracts-detail", kwargs={"pk": cid}))
    assert resp.status_code == 404
