"""Farmer-facing consent control (PRD privacy: grant/revoke per partner).

These run under normal Gitako-user auth + tenant scope (X-Tenant-Id), so an
owner/manager controls which partners can see their farm and what scopes.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm, StaffMembership

from . import models as m

MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


class FarmConsentView(APIView):
    """GET active grants for the farm; POST to grant/update; DELETE to revoke.

    POST body: {partner_id, scopes: [...]}.
    DELETE body/query: {partner_id}.
    """

    permission_classes = [IsAuthenticated]

    def _farm_as_manager(self, request) -> Farm:
        from rest_framework.exceptions import PermissionDenied
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        farm = get_object_or_404(Farm, pk=tenant_id)
        membership = StaffMembership.objects.filter(
            user=request.user, farm=farm,
        ).only("role").first()
        if not membership or membership.role not in MANAGER_ROLES:
            raise PermissionDenied("Only owners and managers can manage data sharing.")
        return farm

    def get(self, request):
        farm = self._farm_as_manager(request)
        grants = m.ConsentGrant.objects.filter(farm=farm).select_related("partner")
        return Response({
            "grants": [
                {
                    "partner_id": str(g.partner_id),
                    "partner_name": g.partner.name,
                    "scopes": g.scopes,
                    "is_active": g.is_active,
                }
                for g in grants
            ],
        })

    def post(self, request):
        from rest_framework.exceptions import ValidationError
        farm = self._farm_as_manager(request)
        partner_id = request.data.get("partner_id")
        scopes = request.data.get("scopes") or []
        if not partner_id:
            raise ValidationError("partner_id is required.")
        bad = set(scopes) - m.ALL_SCOPES
        if bad:
            raise ValidationError(f"Unknown scopes: {sorted(bad)}")
        partner = get_object_or_404(m.Partner, pk=partner_id, is_active=True)
        grant, _ = m.ConsentGrant.objects.update_or_create(
            partner=partner, farm=farm,
            defaults={"scopes": list(scopes), "is_active": True, "revoked_at": None},
        )
        return Response({"partner_id": str(partner.id), "scopes": grant.scopes, "is_active": True})

    def delete(self, request):
        from rest_framework.exceptions import ValidationError
        farm = self._farm_as_manager(request)
        partner_id = request.data.get("partner_id") or request.query_params.get("partner_id")
        if not partner_id:
            raise ValidationError("partner_id is required.")
        m.ConsentGrant.objects.filter(farm=farm, partner_id=partner_id).update(
            is_active=False, revoked_at=timezone.now(),
        )
        return Response(status=204)
