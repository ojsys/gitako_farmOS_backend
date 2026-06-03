"""Officer-access boundary check."""
from __future__ import annotations

from .models import OfficerAccess


def officer_active_farm_ids(officer):
    return OfficerAccess.objects.filter(
        officer=officer, status=OfficerAccess.STATUS_ACTIVE,
    ).values_list("farm_id", flat=True)


def has_active_access(officer, farm_id) -> bool:
    return OfficerAccess.objects.filter(
        officer=officer, farm_id=farm_id, status=OfficerAccess.STATUS_ACTIVE,
    ).exists()
