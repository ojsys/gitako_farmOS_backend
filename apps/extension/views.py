"""Extension Officer / Vet endpoints (PRD M15).

Two surfaces:
- **Officer-facing** (the logged-in user acting as an officer across farms they
  have active access to): roster, request access, issue advisory, schedule/record
  visits, aggregate report.
- **Farmer-facing** (owner/manager of the active tenant farm): approve/revoke
  officer access, read advisories on their own farm.
"""
from __future__ import annotations

from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.enterprises.models import Enterprise
from apps.farms.models import Farm, StaffMembership
from apps.notifications.dispatch import notify
from apps.notifications.models import Notification

from .access import has_active_access, officer_active_farm_ids
from .models import Advisory, OfficerAccess, Visit
from .serializers import AdvisorySerializer, OfficerAccessSerializer, VisitSerializer

MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


def _assert_officer_access(user, farm_id):
    if not has_active_access(user, farm_id):
        raise PermissionDenied("You don't have active access to this farm.")


# ---------- Officer-facing ----------

class OfficerRosterView(APIView):
    """GET → the farms this officer can act on (active access only)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        access = (
            OfficerAccess.objects.filter(officer=request.user, status=OfficerAccess.STATUS_ACTIVE)
            .select_related("farm")
        )
        return Response({"farms": OfficerAccessSerializer(access, many=True).data})


class OfficerRequestAccessView(APIView):
    """POST {farm_id, program?} → create a pending access request for the farmer to approve."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        farm_id = request.data.get("farm_id")
        if not farm_id:
            raise ValidationError("farm_id is required.")
        farm = get_object_or_404(Farm, pk=farm_id, deleted_at__isnull=True)
        access, created = OfficerAccess.objects.get_or_create(
            officer=request.user, farm=farm,
            defaults={"program": request.data.get("program", "")},
        )
        if created:
            # Notify the farm owner so they can approve.
            notify(
                user=farm.owner,
                type=Notification.TYPE_CUSTOM,
                title="Extension officer requested access",
                body=f"{request.user.full_name or request.user.phone} wants to advise your farm.",
                dedupe_key=f"officer-request:{access.id}",
                tenant_id=farm.id,
                data={"officer_access_id": str(access.id)},
            )
        return Response(OfficerAccessSerializer(access).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class OfficerAdvisoryView(APIView):
    """POST {farm_id, title, body?, severity?} → issue an advisory to a consented farm."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        farm_id = request.data.get("farm_id")
        title = (request.data.get("title") or "").strip()
        if not farm_id or not title:
            raise ValidationError("farm_id and title are required.")
        _assert_officer_access(request.user, farm_id)
        farm = get_object_or_404(Farm, pk=farm_id)
        advisory = Advisory.objects.create(
            officer=request.user, farm=farm, title=title,
            body=request.data.get("body", ""),
            severity=request.data.get("severity", "info"),
        )
        # Officer-to-farm messaging rides the notification channel.
        notify(
            user=farm.owner,
            type=Notification.TYPE_CUSTOM,
            title=f"Advisory: {title}",
            body=advisory.body or "",
            dedupe_key=f"advisory:{advisory.id}",
            tenant_id=farm.id,
            data={"advisory_id": str(advisory.id), "severity": advisory.severity},
            channels=("in_app", "sms") if advisory.severity == "urgent" else ("in_app",),
        )
        return Response(AdvisorySerializer(advisory).data, status=status.HTTP_201_CREATED)


class OfficerVisitViewSet(viewsets.ModelViewSet):
    """Officer schedules / records visits to farms they have access to."""

    serializer_class = VisitSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Visit.objects.filter(officer=self.request.user).select_related("farm")

    def perform_create(self, serializer):
        farm = serializer.validated_data["farm"]
        _assert_officer_access(self.request.user, farm.id)
        serializer.save(officer=self.request.user)

    def perform_update(self, serializer):
        _assert_officer_access(self.request.user, self.get_object().farm_id)
        serializer.save()


class OfficerAggregateReportView(APIView):
    """Aggregate rollup across all farms the officer advises (for ADPs / NGOs)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        farm_ids = list(officer_active_farm_ids(request.user))
        enterprises = Enterprise.objects.filter(farm_id__in=farm_ids, deleted_at__isnull=True)
        by_type = dict(
            enterprises.values_list("type").annotate(n=Count("id")).values_list("type", "n")
        )
        return Response({
            "farm_count": len(farm_ids),
            "enterprise_count": enterprises.count(),
            "active_enterprise_count": enterprises.filter(lifecycle_state="active").count(),
            "enterprises_by_type": by_type,
            "advisories_issued": Advisory.objects.filter(officer=request.user).count(),
            "visits_scheduled": Visit.objects.filter(
                officer=request.user, status=Visit.STATUS_SCHEDULED,
            ).count(),
        })


# ---------- Farmer-facing (tenant-scoped) ----------

class FarmOfficerAccessView(APIView):
    """Owner/manager approves or revokes officer access to their farm.

    GET → access requests + grants for the farm.
    POST {officer_access_id, action: approve|revoke}.
    """

    permission_classes = [IsAuthenticated]

    def _farm_as_manager(self, request) -> Farm:
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        farm = get_object_or_404(Farm, pk=tenant_id)
        membership = StaffMembership.objects.filter(
            user=request.user, farm=farm,
        ).only("role").first()
        if not membership or membership.role not in MANAGER_ROLES:
            raise PermissionDenied("Only owners and managers can manage officer access.")
        return farm

    def get(self, request):
        farm = self._farm_as_manager(request)
        access = OfficerAccess.objects.filter(farm=farm).select_related("officer")
        return Response({"access": OfficerAccessSerializer(access, many=True).data})

    def post(self, request):
        farm = self._farm_as_manager(request)
        access_id = request.data.get("officer_access_id")
        verb = request.data.get("action")
        if verb not in {"approve", "revoke"}:
            raise ValidationError("action must be 'approve' or 'revoke'.")
        access = get_object_or_404(OfficerAccess, pk=access_id, farm=farm)
        if verb == "approve":
            access.status = OfficerAccess.STATUS_ACTIVE
            access.approved_at = timezone.now()
        else:
            access.status = OfficerAccess.STATUS_REVOKED
        access.save(update_fields=["status", "approved_at"])
        return Response(OfficerAccessSerializer(access).data)


class FarmAdvisoriesView(APIView):
    """Advisories issued to the active farm (read by owner/manager/staff)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        # any member of the farm can read advisories
        if not StaffMembership.objects.filter(user=request.user, farm_id=tenant_id).exists():
            raise PermissionDenied("You don't have access to this farm.")
        advisories = Advisory.objects.filter(farm_id=tenant_id).select_related("officer")
        return Response({"advisories": AdvisorySerializer(advisories, many=True).data})
