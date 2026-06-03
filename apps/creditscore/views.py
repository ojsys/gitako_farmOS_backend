from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm, StaffMembership

from .engine import compute_score


class MyScoreView(APIView):
    """The active farm's own credit score + full breakdown. Any member reads."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from rest_framework.exceptions import PermissionDenied
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        if not StaffMembership.objects.filter(user=request.user, farm_id=tenant_id).exists():
            raise PermissionDenied("You don't have access to this farm.")
        farm = get_object_or_404(Farm, pk=tenant_id)
        return Response(compute_score(farm))
