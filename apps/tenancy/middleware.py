"""Tenant resolution middleware.

Resolves the active tenant (= Farm) from one of:
  1. `X-Tenant-Id` request header (mobile + web set this on every authed call).
  2. A `?tenant=` query string (for tools / docs).
  3. The user's only farm if they have exactly one.

Authenticated views must have a resolved tenant unless they opt out with
`view.tenant_optional = True`. Sync push/pull validates this strictly.
"""
from __future__ import annotations

import uuid
from typing import Callable

from django.http import HttpRequest, HttpResponse


def _parse_uuid(raw: str | None) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        return None


class TenantMiddleware:
    """Resolve `request.tenant_id` on every request.

    Does NOT enforce membership — that's the view layer's job, because permission
    requirements vary (e.g. /api/auth/me has no tenant; /api/sync/* requires one).
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        tenant_id = (
            _parse_uuid(request.headers.get("X-Tenant-Id"))
            or _parse_uuid(request.GET.get("tenant"))
        )
        if tenant_id is None and getattr(request.user, "is_authenticated", False):
            # If the user has exactly one farm, default to it. Avoids forcing the
            # mobile client to set X-Tenant-Id during onboarding before any farm
            # has been picked.
            try:
                from apps.farms.models import StaffMembership

                memberships = StaffMembership.objects.filter(user=request.user).values_list(
                    "farm_id", flat=True
                )[:2]
                if len(memberships) == 1:
                    tenant_id = memberships[0]
            except Exception:  # noqa: BLE001 — farms app may not be migrated yet
                pass
        request.tenant_id = tenant_id
        return self.get_response(request)
