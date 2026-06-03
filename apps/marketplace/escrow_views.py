"""Offer + escrow contract endpoints (PRD M17).

Authorization model:
  - Any authenticated user can make an Offer on an active listing (the buyer).
  - The seller (owner/manager of the listing's farm) accepts/declines offers.
  - Buyer funds escrow; seller marks delivered; buyer records QA; either party's
    appropriate action releases or refunds.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.farms.models import StaffMembership

from . import escrow
from .escrow_serializers import ContractSerializer, OfferSerializer
from .models import Contract, Listing, Offer

MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


def _is_seller(user, farm) -> bool:
    return StaffMembership.objects.filter(
        user=user, farm=farm, role__in=MANAGER_ROLES,
    ).exists()


class OfferViewSet(viewsets.ModelViewSet):
    """Buyers create offers; sellers accept/decline. Visible to both sides."""

    serializer_class = OfferSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        # Offers I made, or offers on listings owned by farms I manage.
        my_farm_ids = StaffMembership.objects.filter(
            user=user, role__in=MANAGER_ROLES,
        ).values_list("farm_id", flat=True)
        from django.db.models import Q
        return Offer.objects.filter(
            Q(buyer=user) | Q(listing__farm_id__in=my_farm_ids)
        ).select_related("listing").distinct()

    def perform_create(self, serializer):
        listing = serializer.validated_data["listing"]
        if listing.status != Listing.STATUS_ACTIVE:
            raise ValidationError("Listing is not active.")
        if _is_seller(self.request.user, listing.farm):
            raise ValidationError("You can't make an offer on your own listing.")
        serializer.save(buyer=self.request.user)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        offer = get_object_or_404(Offer, pk=pk)
        if not _is_seller(request.user, offer.listing.farm):
            raise PermissionDenied("Only the seller can accept this offer.")
        try:
            contract = escrow.accept_offer(offer)
        except escrow.EscrowError as e:
            raise ValidationError(str(e))
        return Response(ContractSerializer(contract).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="decline")
    def decline(self, request, pk=None):
        offer = get_object_or_404(Offer, pk=pk)
        if not _is_seller(request.user, offer.listing.farm):
            raise PermissionDenied("Only the seller can decline this offer.")
        offer.status = Offer.STATUS_DECLINED
        offer.save(update_fields=["status", "updated_at"])
        return Response(OfferSerializer(offer).data)


class ContractViewSet(viewsets.ReadOnlyModelViewSet):
    """Escrow contracts. Both buyer and seller see their own; transitions via
    explicit actions that enforce who may do what."""

    serializer_class = ContractSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        my_farm_ids = StaffMembership.objects.filter(
            user=user, role__in=MANAGER_ROLES,
        ).values_list("farm_id", flat=True)
        from django.db.models import Q
        return Contract.objects.filter(
            Q(buyer=user) | Q(seller_farm_id__in=my_farm_ids)
        ).select_related("listing", "seller_farm").distinct()

    def _contract(self, pk) -> Contract:
        return get_object_or_404(self.get_queryset(), pk=pk)

    def _run(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except escrow.EscrowError as e:
            raise ValidationError(str(e))

    @action(detail=True, methods=["post"], url_path="fund")
    def fund(self, request, pk=None):
        contract = self._contract(pk)
        if contract.buyer_id != request.user.id:
            raise PermissionDenied("Only the buyer funds escrow.")
        return Response(ContractSerializer(self._run(escrow.fund_escrow, contract)).data)

    @action(detail=True, methods=["post"], url_path="deliver")
    def deliver(self, request, pk=None):
        contract = self._contract(pk)
        if not _is_seller(request.user, contract.seller_farm):
            raise PermissionDenied("Only the seller marks delivery.")
        return Response(ContractSerializer(self._run(escrow.mark_delivered, contract)).data)

    @action(detail=True, methods=["post"], url_path="qa")
    def qa(self, request, pk=None):
        contract = self._contract(pk)
        if contract.buyer_id != request.user.id:
            raise PermissionDenied("Only the buyer records QA at pickup.")
        passed = bool(request.data.get("passed"))
        contract = self._run(escrow.record_qa, contract, passed=passed,
                             notes=request.data.get("notes", ""))
        return Response(ContractSerializer(contract).data)

    @action(detail=True, methods=["post"], url_path="release")
    def release(self, request, pk=None):
        contract = self._contract(pk)
        # Buyer releases (confirms satisfaction); seller cannot self-release.
        if contract.buyer_id != request.user.id:
            raise PermissionDenied("Only the buyer releases escrow.")
        return Response(ContractSerializer(self._run(escrow.release_funds, contract)).data)

    @action(detail=True, methods=["post"], url_path="refund")
    def refund(self, request, pk=None):
        contract = self._contract(pk)
        # Either party can trigger a refund-to-buyer to resolve a dispute; in v1
        # we let the seller concede or the buyer reclaim a funded-but-undelivered deal.
        is_party = contract.buyer_id == request.user.id or _is_seller(request.user, contract.seller_farm)
        if not is_party:
            raise PermissionDenied("Not a party to this contract.")
        return Response(ContractSerializer(self._run(escrow.refund_buyer, contract)).data)
