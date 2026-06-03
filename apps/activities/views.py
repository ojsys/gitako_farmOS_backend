from __future__ import annotations

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.farms.models import StaffMembership
from apps.tenancy.permissions import (
    assert_can_create,
    assert_can_modify,
    role_for,
)

from .models import Activity
from .serializers import ActivitySerializer

TABLE = "activities_activity"


class ActivityViewSet(viewsets.ModelViewSet):
    serializer_class = ActivitySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        qs = Activity.objects.all()
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        else:
            farm_ids = StaffMembership.objects.filter(user=self.request.user).values_list(
                "farm_id", flat=True
            )
            qs = qs.filter(enterprise__farm_id__in=farm_ids)
        enterprise = self.request.query_params.get("enterprise")
        if enterprise:
            qs = qs.filter(enterprise_id=enterprise)
        return qs.order_by("-occurred_at")

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        enterprise = serializer.validated_data["enterprise"]
        if str(enterprise.tenant_id) != str(tenant_id):
            raise PermissionDenied("Enterprise and tenant mismatch.")
        assert_can_create(role_for(self.request.user, tenant_id), TABLE)
        # Default `performed_by` to the recorder when not explicitly set, so
        # every activity always has someone to attribute the work to.
        extras: dict = {"tenant_id": tenant_id, "actor_user": self.request.user}
        if not serializer.validated_data.get("performed_by"):
            extras["performed_by"] = self.request.user
        serializer.save(**extras)

    def perform_update(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        assert_can_modify(
            role_for(self.request.user, tenant_id),
            instance=self.get_object(), user=self.request.user, table=TABLE,
        )
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        tenant_id = getattr(self.request, "tenant_id", None)
        assert_can_modify(
            role_for(self.request.user, tenant_id),
            instance=instance, user=self.request.user, table=TABLE,
        )
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        activity = self.get_object()
        tenant_id = activity.enterprise.farm_id
        role = role_for(request.user, tenant_id)
        # Approval requires owner or manager — distinct from "can modify".
        if role not in {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}:
            raise PermissionDenied("Only owners/managers can approve.")
        activity.approved_at = timezone.now()
        activity.approved_by = request.user
        activity.save(update_fields=["approved_at", "approved_by", "updated_at"])
        return Response(ActivitySerializer(activity).data)
