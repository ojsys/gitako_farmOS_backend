"""M20 Developer App Store — browse, install (paid split via payments seam), uninstall."""
from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.devstore.models import DeveloperModule, ModuleInstall
from apps.farms.models import Farm, StaffMembership
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
def developer():
    return Partner.objects.create(name="VetConnect", kind="other")


@pytest.fixture
def free_module(developer):
    return DeveloperModule.objects.create(developer=developer, name="Vet Booking",
                                          slug="vet-booking", category="vet",
                                          price_kobo=0, status="published")


@pytest.fixture
def paid_module(developer):
    return DeveloperModule.objects.create(developer=developer, name="Soil Testing",
                                          slug="soil-testing", category="soil_testing",
                                          price_kobo=10_000_00, revenue_share_pct=20,
                                          status="published")


def test_browse_lists_published_only(authed, developer, free_module):
    DeveloperModule.objects.create(developer=developer, name="Hidden", slug="hidden",
                                   status="draft")
    resp = authed.get(reverse("modules-list"))
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    slugs = {r["slug"] for r in rows}
    assert "vet-booking" in slugs
    assert "hidden" not in slugs


def test_browse_filters_by_category(authed, paid_module):
    resp = authed.get(reverse("modules-list"), {"category": "soil_testing"})
    rows = resp.json()["results"] if isinstance(resp.json(), dict) else resp.json()
    assert all(r["category"] == "soil_testing" for r in rows)


def test_install_free_module(authed, farm, free_module):
    resp = authed.post(reverse("installs-install"), {"module_id": str(free_module.id)}, format="json")
    assert resp.status_code == 201, resp.content
    assert ModuleInstall.objects.filter(module=free_module, farm=farm, is_active=True).exists()


def test_install_paid_module_splits_revenue(authed, farm, paid_module):
    resp = authed.post(reverse("installs-install"), {"module_id": str(paid_module.id)}, format="json")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    # 20% of 10,000.00 = 2,000.00 to Gitako; 8,000.00 to dev.
    assert body["gitako_cut_kobo"] == 2_000_00
    assert body["developer_take_kobo"] == 8_000_00
    assert body["payment_reference"] != ""


def test_double_install_rejected(authed, farm, free_module):
    authed.post(reverse("installs-install"), {"module_id": str(free_module.id)}, format="json")
    resp = authed.post(reverse("installs-install"), {"module_id": str(free_module.id)}, format="json")
    assert resp.status_code == 400


def test_install_requires_manager(api_client, farm, free_module):
    staff = User.objects.create_user(phone="+2348010000077")
    StaffMembership.objects.create(user=staff, farm=farm, role=StaffMembership.ROLE_FIELD)
    api_client.force_authenticate(user=staff)
    api_client.credentials(HTTP_X_TENANT_ID=str(farm.id))
    resp = api_client.post(reverse("installs-install"), {"module_id": str(free_module.id)}, format="json")
    assert resp.status_code == 403


def test_uninstall(authed, farm, free_module):
    install_id = authed.post(reverse("installs-install"),
                             {"module_id": str(free_module.id)}, format="json").json()["id"]
    resp = authed.post(reverse("installs-uninstall", kwargs={"pk": install_id}))
    assert resp.status_code == 204
    ModuleInstall.objects.get(pk=install_id).refresh_from_db()
    assert not ModuleInstall.objects.get(pk=install_id).is_active
