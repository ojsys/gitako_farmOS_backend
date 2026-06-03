from __future__ import annotations

import uuid

from django.db import transaction as db_transaction
from django.db.models import Sum
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
from apps.tenancy.permissions import (
    assert_can_create,
    assert_can_modify,
    role_for,
)

from .models import Account, Transaction
from .serializers import AccountSerializer, TransactionSerializer, _balance_kobo

ACCOUNT_TABLE = "finance_account"
TRANSACTION_TABLE = "finance_transaction"


def _user_farm_ids(user):
    return StaffMembership.objects.filter(user=user).values_list("farm_id", flat=True)


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]
    queryset = Account.objects.all()

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        qs = self.queryset.filter(deleted_at__isnull=True)
        if tenant_id is not None:
            return qs.filter(tenant_id=tenant_id)
        return qs.filter(tenant_id__in=_user_farm_ids(self.request.user))

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(self.request.user, tenant_id), ACCOUNT_TABLE)
        farm = get_object_or_404(Farm, pk=tenant_id)
        serializer.save(tenant_id=tenant_id, farm=farm)

    def perform_update(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        assert_can_modify(
            role_for(self.request.user, tenant_id),
            instance=self.get_object(), user=self.request.user, table=ACCOUNT_TABLE,
        )
        serializer.save()


class TransactionViewSet(viewsets.ModelViewSet):
    """REST CRUD for transactions plus a /transfer convenience that creates the
    paired rows atomically. Mirrors inventory's transfer endpoint.
    """

    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    queryset = Transaction.objects.select_related("account", "party", "enterprise").all()

    def get_queryset(self):
        tenant_id = getattr(self.request, "tenant_id", None)
        qs = self.queryset.filter(deleted_at__isnull=True)
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        else:
            qs = qs.filter(tenant_id__in=_user_farm_ids(self.request.user))
        if (account := self.request.query_params.get("account")):
            qs = qs.filter(account_id=account)
        if (enterprise := self.request.query_params.get("enterprise")):
            qs = qs.filter(enterprise_id=enterprise)
        return qs.order_by("-posted_at")

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(self.request.user, tenant_id), TRANSACTION_TABLE)
        data = serializer.validated_data
        # Normalize sign by kind so the client doesn't have to.
        amount = data.get("amount_kobo", 0)
        kind = data.get("kind")
        if kind == Transaction.KIND_EXPENSE and amount > 0:
            data["amount_kobo"] = -amount
        if kind == Transaction.KIND_INCOME and amount < 0:
            data["amount_kobo"] = -amount
        farm = get_object_or_404(Farm, pk=tenant_id)
        serializer.save(tenant_id=tenant_id, farm=farm)

    @action(detail=False, methods=["post"], url_path="transfer")
    def transfer(self, request):
        """Body: {from_account, to_account, amount_kobo, posted_at?, description?}."""
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(request.user, tenant_id), TRANSACTION_TABLE)

        src = request.data.get("from_account")
        dst = request.data.get("to_account")
        amount = request.data.get("amount_kobo")
        if not (src and dst and amount):
            raise ValidationError("from_account, to_account, amount_kobo required.")
        if src == dst:
            raise ValidationError("from_account and to_account must differ.")
        try:
            amt = int(amount)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid amount: {amount}") from exc
        if amt <= 0:
            raise ValidationError("amount_kobo must be positive for a transfer.")

        farm = get_object_or_404(Farm, pk=tenant_id)
        pair = uuid.uuid4()
        posted_at = request.data.get("posted_at") or timezone.now().isoformat()
        desc = request.data.get("description", "")

        with db_transaction.atomic():
            out_row = Transaction.objects.create(
                tenant_id=tenant_id, farm=farm, account_id=src,
                kind=Transaction.KIND_TRANSFER, amount_kobo=-amt,
                transfer_pair_id=pair, posted_at=posted_at, description=desc,
            )
            in_row = Transaction.objects.create(
                tenant_id=tenant_id, farm=farm, account_id=dst,
                kind=Transaction.KIND_TRANSFER, amount_kobo=amt,
                transfer_pair_id=pair, posted_at=posted_at, description=desc,
            )
        return Response(
            TransactionSerializer([out_row, in_row], many=True).data,
            status=status.HTTP_201_CREATED,
        )


class CashPositionView(APIView):
    """{by_account: [{account_id, name, type, balance_kobo}], total_kobo}."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        rows = []
        total = 0
        for acc in Account.objects.filter(
            tenant_id=tenant_id, deleted_at__isnull=True,
        ).order_by("name"):
            bal = _balance_kobo(acc)
            total += bal
            rows.append({
                "account_id": str(acc.id),
                "name": acc.name,
                "type": acc.type,
                "balance_kobo": bal,
            })
        return Response({"by_account": rows, "total_kobo": total})


class PnlView(APIView):
    """Money-in / money-out / net per enterprise, plus farm totals.

    Query params:
      enterprise=<id>  — filter to one enterprise (full detail in `by_enterprise`)
      from=<iso>       — start of window (inclusive)
      to=<iso>         — end of window (exclusive)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        qs = Transaction.objects.filter(tenant_id=tenant_id, deleted_at__isnull=True)
        if (f := request.query_params.get("from")):
            qs = qs.filter(posted_at__gte=f)
        if (t := request.query_params.get("to")):
            qs = qs.filter(posted_at__lt=t)
        if (e := request.query_params.get("enterprise")):
            qs = qs.filter(enterprise_id=e)

        # Farm-wide totals (income = positive amounts, expense = negative)
        money_in = qs.filter(amount_kobo__gt=0, kind=Transaction.KIND_INCOME) \
            .aggregate(s=Sum("amount_kobo"))["s"] or 0
        money_out = -(qs.filter(amount_kobo__lt=0, kind=Transaction.KIND_EXPENSE) \
            .aggregate(s=Sum("amount_kobo"))["s"] or 0)

        # Per-enterprise rollup
        per_ent = []
        ent_qs = Enterprise.objects.filter(tenant_id=tenant_id, deleted_at__isnull=True)
        for ent in ent_qs:
            ent_qs_t = qs.filter(enterprise=ent)
            in_kobo = ent_qs_t.filter(amount_kobo__gt=0, kind=Transaction.KIND_INCOME) \
                .aggregate(s=Sum("amount_kobo"))["s"] or 0
            out_kobo = -(ent_qs_t.filter(amount_kobo__lt=0, kind=Transaction.KIND_EXPENSE) \
                .aggregate(s=Sum("amount_kobo"))["s"] or 0)
            if in_kobo == 0 and out_kobo == 0:
                continue
            per_ent.append({
                "enterprise_id": str(ent.id),
                "name": ent.name,
                "type": ent.type,
                "in_kobo": int(in_kobo),
                "out_kobo": int(out_kobo),
                "net_kobo": int(in_kobo - out_kobo),
                "status": "actual" if ent.lifecycle_state == "completed" else "projected",
            })

        return Response({
            "money_in_kobo": int(money_in),
            "money_out_kobo": int(money_out),
            "net_kobo": int(money_in - money_out),
            "by_enterprise": per_ent,
        })
