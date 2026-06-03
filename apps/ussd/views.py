"""USSD gateway webhook (PRD M19).

Telco/aggregator-agnostic. Accepts `phoneNumber` + `text` (Africa's Talking
shape) and replies with the `CON`/`END` prefix USSD gateways expect. AllowAny —
the gateway authenticates via its own shared secret / IP allowlist in prod
(documented for the deploy step); the engine itself only acts for a phone that
maps to a registered Gitako user.
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .engine import process


class UssdGatewayView(APIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request):
        phone = (request.data.get("phoneNumber") or request.data.get("phone") or "").strip()
        text = request.data.get("text", "")
        if not phone:
            return Response("END Missing phone number.", content_type="text/plain", status=400)
        message, should_continue = process(phone, text)
        prefix = "CON" if should_continue else "END"
        return Response(f"{prefix} {message}", content_type="text/plain")
