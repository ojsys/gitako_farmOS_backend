"""Partner read API (PRD M14).

Every endpoint:
  - authenticates the partner via API key,
  - resolves the target farm,
  - checks an active ConsentGrant covering the required scope,
  - writes a PartnerAuditEntry,
  - returns only data permitted by that scope.

Aggregate data is anonymized rollups (counts/totals) — no row-level detail.
Activity events expose type + timestamp only (no notes, photos, or GPS).
"""
from __future__ import annotations

from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.activities.models import Activity
from apps.enterprises.models import Enterprise
from apps.farms.models import Farm
from apps.finance.models import Transaction

from . import models as m
from .auth import PartnerApiKeyAuthentication, PartnerRateThrottle


class _PartnerView(APIView):
    """Base: API-key auth + per-partner throttle. No Gitako-user permission —
    access is governed entirely by consent, checked per-handler."""

    authentication_classes = [PartnerApiKeyAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [PartnerRateThrottle]
    required_scope: str = ""

    def _consented_farm(self, request, farm_id) -> Farm:
        from rest_framework.exceptions import NotFound, PermissionDenied

        partner = getattr(request, "partner", None)
        if partner is None:
            raise PermissionDenied("Partner authentication required.")
        farm = get_object_or_404(Farm, pk=farm_id, deleted_at__isnull=True)
        grant = m.ConsentGrant.objects.filter(partner=partner, farm=farm).first()
        if grant is None or not grant.allows(self.required_scope):
            self._audit(request, farm, status_code=403)
            raise PermissionDenied(
                f"This farm has not granted '{self.required_scope}' access to your organization."
            )
        return farm

    def _audit(self, request, farm, status_code=200):
        partner = getattr(request, "partner", None)
        if partner is None:
            return
        m.PartnerAuditEntry.objects.create(
            partner=partner, path=request.path, farm=farm,
            scope=self.required_scope, status_code=status_code,
        )


class FarmRegistryView(_PartnerView):
    required_scope = m.SCOPE_REGISTRY

    def get(self, request, farm_id):
        farm = self._consented_farm(request, farm_id)
        self._audit(request, farm)
        return Response({
            "farm_id": str(farm.id),
            "name": farm.name,
            "region": farm.region,
            "modules_enabled": farm.modules_enabled,
            "owner_phone": farm.owner.phone,
            "created_at": farm.created_at.isoformat(),
        })


class FarmAggregateView(_PartnerView):
    required_scope = m.SCOPE_AGGREGATE

    def get(self, request, farm_id):
        farm = self._consented_farm(request, farm_id)
        self._audit(request, farm)
        enterprises = Enterprise.objects.filter(farm=farm, deleted_at__isnull=True)
        txns = Transaction.objects.filter(tenant_id=farm.id, deleted_at__isnull=True)
        income = txns.filter(amount_kobo__gt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0
        expense = -(txns.filter(amount_kobo__lt=0).aggregate(s=Sum("amount_kobo"))["s"] or 0)
        activity_count = Activity.objects.filter(tenant_id=farm.id, deleted_at__isnull=True).count()
        # Anonymized rollups only — no per-row detail.
        return Response({
            "farm_id": str(farm.id),
            "enterprise_count": enterprises.count(),
            "active_enterprise_count": enterprises.filter(lifecycle_state="active").count(),
            "enterprise_types": list(enterprises.values_list("type", flat=True).distinct()),
            "activity_count": activity_count,
            "total_income_kobo": int(income),
            "total_expense_kobo": int(expense),
            "net_kobo": int(income - expense),
        })


class ActivityEventsView(_PartnerView):
    required_scope = m.SCOPE_ACTIVITY

    def get(self, request, farm_id):
        farm = self._consented_farm(request, farm_id)
        self._audit(request, farm)
        # type + timestamp + enterprise id only — no notes, photos, GPS, cost.
        events = (
            Activity.objects.filter(tenant_id=farm.id, deleted_at__isnull=True)
            .order_by("-occurred_at")[:200]
            .values("id", "type", "enterprise_id", "occurred_at")
        )
        return Response({
            "farm_id": str(farm.id),
            "events": [
                {
                    "id": str(e["id"]),
                    "type": e["type"],
                    "enterprise_id": str(e["enterprise_id"]) if e["enterprise_id"] else None,
                    "occurred_at": e["occurred_at"].isoformat(),
                }
                for e in events
            ],
        })


class CreditScoreView(_PartnerView):
    required_scope = m.SCOPE_CREDIT

    def get(self, request, farm_id):
        farm = self._consented_farm(request, farm_id)
        self._audit(request, farm)
        from apps.creditscore.engine import compute_score
        result = compute_score(farm)
        # Partners get the headline score + band only — not the full breakdown.
        return Response({
            "farm_id": result["farm_id"],
            "score": result["score"],
            "band": result["band"],
            "max_score": result["max_score"],
            "computed_at": result["computed_at"],
        })


class PartnerConsentsView(_PartnerView):
    """List the farms that have granted this partner access (any scope)."""

    required_scope = ""  # listing own grants needs no per-farm scope

    def get(self, request):
        from rest_framework.exceptions import PermissionDenied
        partner = getattr(request, "partner", None)
        if partner is None:
            raise PermissionDenied("Partner authentication required.")
        grants = m.ConsentGrant.objects.filter(
            partner=partner, is_active=True,
        ).select_related("farm")
        return Response({
            "farms": [
                {"farm_id": str(g.farm_id), "name": g.farm.name, "scopes": g.scopes}
                for g in grants
            ],
        })
