"""Embedded finance endpoints (PRD M18) — farmer-facing, tenant-scoped.

Owners/managers apply for loans, request insurance quotes, and request input
financing. Loan transitions (submit/accept/disburse/repay) are explicit actions.
Partner-side offer/decline is exposed too — in the closed beta a manager can
drive it; in production the partner portal (M14) calls these.
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.farms.models import Farm, StaffMembership
from apps.partners.models import Partner

from . import service
from .models import InputFinancing, InsuranceQuote, LoanApplication
from .serializers import (
    InputFinancingSerializer,
    InsuranceQuoteSerializer,
    LoanApplicationSerializer,
)

MANAGER_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}


def _farm_as_manager(request) -> Farm:
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        raise PermissionDenied("X-Tenant-Id header required.")
    farm = get_object_or_404(Farm, pk=tenant_id)
    membership = StaffMembership.objects.filter(user=request.user, farm=farm).only("role").first()
    if not membership or membership.role not in MANAGER_ROLES:
        raise PermissionDenied("Only owners and managers can manage farm finance.")
    return farm


class _FarmScopedFinanceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            return self.queryset.none()
        return self.queryset.filter(farm_id=tenant_id)

    def perform_create(self, serializer):
        farm = _farm_as_manager(self.request)
        serializer.save(farm=farm)


class LoanApplicationViewSet(_FarmScopedFinanceViewSet):
    serializer_class = LoanApplicationSerializer
    queryset = LoanApplication.objects.all()

    def perform_create(self, serializer):
        farm = _farm_as_manager(self.request)
        serializer.save(farm=farm, applicant=self.request.user)

    def _run(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except service.FinanceError as e:
            raise ValidationError(str(e))

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        loan = self.get_object()
        _farm_as_manager(request)
        partner = None
        if (pid := request.data.get("partner_id")):
            partner = get_object_or_404(Partner, pk=pid, is_active=True)
        loan = self._run(service.submit_loan, loan, partner=partner)
        return Response(LoanApplicationSerializer(loan).data)

    @action(detail=True, methods=["post"], url_path="offer")
    def offer(self, request, pk=None):
        loan = self.get_object()
        _farm_as_manager(request)
        loan = self._run(service.offer_loan, loan, terms=request.data.get("terms", {}))
        return Response(LoanApplicationSerializer(loan).data)

    @action(detail=True, methods=["post"], url_path="accept")
    def accept(self, request, pk=None):
        loan = self.get_object()
        _farm_as_manager(request)
        return Response(LoanApplicationSerializer(self._run(service.accept_loan, loan)).data)

    @action(detail=True, methods=["post"], url_path="disburse")
    def disburse(self, request, pk=None):
        loan = self.get_object()
        _farm_as_manager(request)
        return Response(LoanApplicationSerializer(self._run(service.disburse_loan, loan)).data)

    @action(detail=True, methods=["post"], url_path="repay")
    def repay(self, request, pk=None):
        loan = self.get_object()
        _farm_as_manager(request)
        return Response(LoanApplicationSerializer(self._run(service.repay_loan, loan)).data)


class InsuranceQuoteViewSet(_FarmScopedFinanceViewSet):
    serializer_class = InsuranceQuoteSerializer
    queryset = InsuranceQuote.objects.all()

    @action(detail=True, methods=["post"], url_path="quote")
    def quote(self, request, pk=None):
        """Partner returns a premium for a requested cover."""
        q = self.get_object()
        _farm_as_manager(request)
        if q.status != InsuranceQuote.STATUS_REQUESTED:
            raise ValidationError("Only a requested quote can be priced.")
        premium = request.data.get("premium_kobo")
        if premium is None:
            raise ValidationError("premium_kobo is required.")
        q.premium_kobo = int(premium)
        q.status = InsuranceQuote.STATUS_QUOTED
        q.save(update_fields=["premium_kobo", "status", "updated_at"])
        return Response(InsuranceQuoteSerializer(q).data)

    @action(detail=True, methods=["post"], url_path="bind")
    def bind(self, request, pk=None):
        q = self.get_object()
        _farm_as_manager(request)
        if q.status != InsuranceQuote.STATUS_QUOTED:
            raise ValidationError("Only a quoted policy can be bound.")
        q.status = InsuranceQuote.STATUS_BOUND
        q.save(update_fields=["status", "updated_at"])
        return Response(InsuranceQuoteSerializer(q).data)


class InputFinancingViewSet(_FarmScopedFinanceViewSet):
    serializer_class = InputFinancingSerializer
    queryset = InputFinancing.objects.all()

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        f = self.get_object()
        _farm_as_manager(request)
        if f.status != InputFinancing.STATUS_REQUESTED:
            raise ValidationError("Only a requested item can be approved.")
        f.status = InputFinancing.STATUS_APPROVED
        f.save(update_fields=["status", "updated_at"])
        return Response(InputFinancingSerializer(f).data)
