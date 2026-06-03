from __future__ import annotations

import uuid

from django.db import transaction as db_transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.farms.models import Farm, StaffMembership
from apps.tenancy.permissions import (
    assert_can_create,
    assert_can_modify,
    role_for,
)

from .models import InventoryItem, InventoryMovement, Store
from .serializers import (
    InventoryItemSerializer,
    InventoryMovementSerializer,
    StoreSerializer,
    _stock_qty,
    _stock_value_kobo,
)

ITEM_TABLE = "inventory_inventoryitem"
STORE_TABLE = "inventory_store"
MOVEMENT_TABLE = "inventory_inventorymovement"


def _user_farm_ids(user):
    return StaffMembership.objects.filter(user=user).values_list("farm_id", flat=True)


class _TenantScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    table_name: str = ""

    def get_queryset(self):
        qs = self.queryset
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is not None:
            return qs.filter(tenant_id=tenant_id)
        return qs.filter(tenant_id__in=_user_farm_ids(self.request.user))

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(self.request.user, tenant_id), self.table_name)
        serializer.save(tenant_id=tenant_id)

    def perform_update(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        assert_can_modify(
            role_for(self.request.user, tenant_id),
            instance=self.get_object(), user=self.request.user,
            table=self.table_name,
        )
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        tenant_id = getattr(request, "tenant_id", None)
        assert_can_modify(
            role_for(request.user, tenant_id),
            instance=instance, user=request.user, table=self.table_name,
        )
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class StoreViewSet(_TenantScopedViewSet):
    serializer_class = StoreSerializer
    queryset = Store.objects.all()
    table_name = STORE_TABLE

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(self.request.user, tenant_id), self.table_name)
        farm = get_object_or_404(Farm, pk=tenant_id)
        serializer.save(tenant_id=tenant_id, farm=farm)


class InventoryItemViewSet(_TenantScopedViewSet):
    serializer_class = InventoryItemSerializer
    queryset = InventoryItem.objects.all()
    table_name = ITEM_TABLE

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(self.request.user, tenant_id), self.table_name)
        farm = get_object_or_404(Farm, pk=tenant_id)
        serializer.save(tenant_id=tenant_id, farm=farm)

    @action(detail=True, methods=["get"], url_path="stock")
    def stock(self, request, pk=None):
        """{ qty_on_hand, value_kobo, by_store: [{store_id, store_name, qty}] }"""
        item = self.get_object()
        by_store = (
            item.movements.filter(deleted_at__isnull=True)
            .values("store_id", "store__name")
            .annotate(qty=Sum("qty"))
            .order_by("store__name")
        )
        return Response({
            "item_id": str(item.id),
            "qty_on_hand": _stock_qty(item),
            "value_kobo": _stock_value_kobo(item),
            "reorder_level": float(item.reorder_level),
            "by_store": [
                {
                    "store_id": str(row["store_id"]),
                    "store_name": row["store__name"],
                    "qty": float(row["qty"] or 0),
                }
                for row in by_store
            ],
        })


class InventoryMovementViewSet(viewsets.ModelViewSet):
    """Movements have two write paths:

    - Plain REST POST (UI form). Body: {item, store, op, qty, unit_cost_kobo, ...}.
    - Convenience action `transfer` that creates the negative/positive pair
      atomically given {item, from_store, to_store, qty, ...}.

    Issues that came from an activity are typically enqueued client-side via
    sync.push along with the activity itself, but the REST endpoint accepts
    them too for admin / corrections.
    """

    serializer_class = InventoryMovementSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = InventoryMovement.objects.select_related("item", "store")
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is not None:
            qs = qs.filter(tenant_id=tenant_id)
        else:
            qs = qs.filter(tenant_id__in=_user_farm_ids(self.request.user))
        item = self.request.query_params.get("item")
        if item:
            qs = qs.filter(item_id=item)
        store = self.request.query_params.get("store")
        if store:
            qs = qs.filter(store_id=store)
        return qs.order_by("-occurred_at")

    def perform_create(self, serializer):
        tenant_id = getattr(self.request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(self.request.user, tenant_id), MOVEMENT_TABLE)
        data = serializer.validated_data
        # Normalize sign by op (issue is negative, others as supplied).
        qty = data.get("qty")
        op = data.get("op")
        if op == InventoryMovement.OP_ISSUE and qty > 0:
            data["qty"] = -qty
        serializer.save(tenant_id=tenant_id)

    @action(detail=False, methods=["post"], url_path="transfer")
    def transfer(self, request):
        """Body: {item, from_store, to_store, qty, occurred_at?, notes?}."""
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        assert_can_create(role_for(request.user, tenant_id), MOVEMENT_TABLE)

        item_id = request.data.get("item")
        from_store = request.data.get("from_store")
        to_store = request.data.get("to_store")
        qty = request.data.get("qty")
        if not (item_id and from_store and to_store and qty):
            raise ValidationError("item, from_store, to_store, qty required.")
        if from_store == to_store:
            raise ValidationError("from_store and to_store must differ.")
        try:
            qty_val = float(qty)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid qty: {qty}") from exc
        if qty_val <= 0:
            raise ValidationError("qty must be positive for a transfer.")

        pair = uuid.uuid4()
        occurred_at = request.data.get("occurred_at") or timezone.now().isoformat()
        notes = request.data.get("notes", "")

        with db_transaction.atomic():
            out_row = InventoryMovement.objects.create(
                tenant_id=tenant_id, item_id=item_id, store_id=from_store,
                op=InventoryMovement.OP_TRANSFER, qty=-qty_val,
                transfer_pair_id=pair, occurred_at=occurred_at, notes=notes,
            )
            in_row = InventoryMovement.objects.create(
                tenant_id=tenant_id, item_id=item_id, store_id=to_store,
                op=InventoryMovement.OP_TRANSFER, qty=qty_val,
                transfer_pair_id=pair, occurred_at=occurred_at, notes=notes,
            )
        return Response(
            InventoryMovementSerializer([out_row, in_row], many=True).data,
            status=status.HTTP_201_CREATED,
        )


class InventorySummaryView(viewsets.ViewSet):
    """Farm-wide totals for the Stores screen + dashboard KPIs."""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if tenant_id is None:
            raise PermissionDenied("X-Tenant-Id header required.")
        items = InventoryItem.objects.filter(
            tenant_id=tenant_id, deleted_at__isnull=True,
        )
        store_count = Store.objects.filter(
            tenant_id=tenant_id, deleted_at__isnull=True,
        ).count()

        total_value = 0
        low_count = 0
        for item in items:
            value = _stock_value_kobo(item)
            total_value += value
            if float(_stock_qty(item)) < float(item.reorder_level):
                low_count += 1

        return Response({
            "store_count": store_count,
            "item_count": items.count(),
            "total_value_kobo": total_value,
            "low_stock_count": low_count,
        })
