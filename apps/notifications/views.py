from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm, StaffMembership

from .models import DigestPreference, Notification, NotificationRule
from .serializers import (
    DigestPreferenceSerializer,
    NotificationRuleSerializer,
    NotificationSerializer,
)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """The current user's notification feed.

    ?unread=true   — only unread
    ?tenant=<id>   — scope to one farm (otherwise all the user's notifications)
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # The feed is a per-user inbox spanning all the user's farms, so we don't
        # auto-scope by the active tenant. Pass ?tenant=<id> to narrow to one farm.
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)
        tenant_id = self.request.query_params.get("tenant")
        if tenant_id:
            qs = qs.filter(tenant_id=tenant_id)
        return qs

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({"unread": count})

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = Notification.objects.filter(user=request.user, is_read=False).update(
            is_read=True, read_at=timezone.now(),
        )
        return Response({"marked": updated})


class DigestPreferenceView(APIView):
    """Get / update the current user's daily-digest preference."""

    permission_classes = [IsAuthenticated]

    def _pref(self, user):
        pref, _ = DigestPreference.objects.get_or_create(user=user)
        return pref

    def get(self, request):
        return Response(DigestPreferenceSerializer(self._pref(request.user)).data)

    def patch(self, request):
        pref = self._pref(request.user)
        serializer = DigestPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class NotificationRuleViewSet(viewsets.ModelViewSet):
    """Per-farm alert thresholds. Scoped to the active tenant; owners/managers only
    may change them."""

    serializer_class = NotificationRuleSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "put", "head", "options"]

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            return NotificationRule.objects.none()
        return NotificationRule.objects.filter(farm_id=tenant_id)

    def _assert_manager(self, tenant_id):
        membership = StaffMembership.objects.filter(
            user=self.request.user, farm_id=tenant_id,
        ).only("role").first()
        if not membership or membership.role not in {
            StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER,
        }:
            raise PermissionDenied("Only owners and managers can change alert rules.")

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        self._assert_manager(tenant_id)
        farm = get_object_or_404(Farm, pk=tenant_id)
        serializer.save(farm=farm)

    def perform_update(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        self._assert_manager(tenant_id)
        serializer.save()
