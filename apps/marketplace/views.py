from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm, StaffMembership

from .models import Listing
from .serializers import ListingSerializer

MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


class ListingBrowseView(viewsets.ReadOnlyModelViewSet):
    """Cross-tenant browse of active listings — any authenticated user.

    Filters: ?kind=, ?region=, ?q= (title/description), ?verified=true.
    This is the marketplace's public-within-the-app surface; it intentionally
    does NOT scope by X-Tenant-Id.
    """

    serializer_class = ListingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Listing.objects.filter(status=Listing.STATUS_ACTIVE).select_related("farm")
        params = self.request.query_params
        if (kind := params.get("kind")):
            qs = qs.filter(kind=kind)
        if (region := params.get("region")):
            qs = qs.filter(region__icontains=region)
        if (q := params.get("q")):
            from django.db.models import Q
            qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
        return qs

    @action(detail=True, methods=["get"], url_path="contact")
    def contact(self, request, pk=None):
        """Reveal the seller's contact (the connection step — no on-platform clearing)."""
        listing = get_object_or_404(Listing, pk=pk, status=Listing.STATUS_ACTIVE)
        return Response({
            "farm_name": listing.farm.name,
            "contact_phone": listing.contact_phone or listing.farm.owner.phone,
            "region": listing.region,
        })


class MyListingViewSet(viewsets.ModelViewSet):
    """Manage the active farm's own listings. Owners + managers only."""

    serializer_class = ListingSerializer
    permission_classes = [IsAuthenticated]

    def _farm(self) -> Farm:
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        return get_object_or_404(Farm, pk=tenant_id)

    def _assert_manager(self, farm):
        membership = StaffMembership.objects.filter(
            user=self.request.user, farm=farm,
        ).only("role").first()
        if not membership or membership.role not in MANAGER_ROLES:
            raise PermissionDenied("Only owners and managers can manage listings.")

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            return Listing.objects.none()
        return Listing.objects.filter(farm_id=tenant_id).select_related("farm")

    def perform_create(self, serializer):
        farm = self._farm()
        self._assert_manager(farm)
        serializer.save(farm=farm)

    def perform_update(self, serializer):
        self._assert_manager(self.get_object().farm)
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        listing = self.get_object()
        self._assert_manager(listing.farm)
        listing.status = Listing.STATUS_WITHDRAWN
        listing.updated_at = timezone.now()
        listing.save(update_fields=["status", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)
