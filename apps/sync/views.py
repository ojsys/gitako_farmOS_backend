"""Sync push/pull DRF views."""
from __future__ import annotations

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import engine
from .models import SyncCursor


def _require_tenant(request):
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        return None, Response(
            {"detail": "X-Tenant-Id header required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return tenant_id, None


def _device_id(request) -> str:
    return request.headers.get("X-Device-Id", "")


class PushView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Push device mutations",
        description="Submit a batch of offline mutations. Returns accepted ops + conflicts.",
    )
    def post(self, request):
        tenant_id, err = _require_tenant(request)
        if err:
            return err
        device_id = _device_id(request)
        try:
            ops = engine.parse_push_body(request.data)
        except (KeyError, ValueError, TypeError) as exc:
            return Response({"detail": f"Bad push body: {exc}"}, status=400)

        try:
            accepted, conflicts = engine.push_batch(
                ops=ops, tenant_id=tenant_id, actor_user=request.user, device_id=device_id
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            {
                "accepted": [{"row_id": str(a.row_id), "server_seq": a.server_seq} for a in accepted],
                "conflicts": [
                    {
                        "row_id": str(c.row_id),
                        "server_payload": c.server_payload,
                        "client_payload": c.client_payload,
                    }
                    for c in conflicts
                ],
            }
        )


class PullView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Pull server changes",
        description="Fetch ChangeLog rows since the given server_seq cursor.",
    )
    def get(self, request):
        tenant_id, err = _require_tenant(request)
        if err:
            return err
        device_id = _device_id(request)
        since = int(request.query_params.get("since", 0))
        limit = min(int(request.query_params.get("limit", 500)), 1000)

        result = engine.pull_changes(tenant_id=tenant_id, since=since, limit=limit)

        # Advance the cursor to what we just delivered.
        cursor, _ = SyncCursor.objects.get_or_create(
            user=request.user, tenant_id=tenant_id, device_id=device_id
        )
        cursor.last_server_seq_acked = result["next_since"]
        cursor.last_pull_at = timezone.now()
        cursor.save()

        return Response(result)
