from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.farms.models import Farm

from . import service

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _require_farm(request) -> Farm:
    tenant_id = getattr(request, "tenant_id", None)
    if tenant_id is None:
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("X-Tenant-Id header required.")
    return get_object_or_404(Farm, pk=tenant_id)


class ChatView(APIView):
    """POST {message, history?} → {reply, used_tools}. Farm-scoped via X-Tenant-Id."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        message = (request.data.get("message") or "").strip()
        if not message:
            return Response({"detail": "message is required."}, status=400)
        farm = _require_farm(request)
        history = request.data.get("history") or []
        result = service.answer_question(
            farm=farm, user=request.user, message=message, history=history,
        )
        return Response(result)


class DiagnoseView(APIView):
    """POST {image_base64, media_type, prompt?} → {diagnosis, confidence, treatment}."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        image_b64 = request.data.get("image_base64")
        media_type = request.data.get("media_type", "image/jpeg")
        if not image_b64:
            return Response({"detail": "image_base64 is required."}, status=400)
        if media_type not in ALLOWED_MEDIA:
            return Response({"detail": f"media_type must be one of {sorted(ALLOWED_MEDIA)}."}, status=400)
        # base64 expands ~4:3; cheap guard against oversized payloads.
        if len(image_b64) > MAX_IMAGE_BYTES * 4 // 3:
            return Response({"detail": "Image too large (max ~5MB)."}, status=413)
        result = service.diagnose_image(
            image_b64=image_b64, media_type=media_type, prompt=request.data.get("prompt", ""),
        )
        return Response(result)


class AnomaliesView(APIView):
    """GET → {anomalies: [...]}. Rules-based flags for the active farm."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        farm = _require_farm(request)
        return Response({"anomalies": service.farm_anomalies(farm=farm)})
