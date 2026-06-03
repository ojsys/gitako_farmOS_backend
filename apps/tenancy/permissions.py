"""Role-based write permissions for tenant-scoped resources.

PRD M1 role matrix:
  owner      — everything (farm, enterprises, activities, money, team)
  manager    — full access; approves records
  field_staff — creates activities, edits/deletes only their own; no farm /
                enterprise / money mutations
  viewer     — read only

This module centralizes the policy so REST viewsets and the sync engine
apply the same rules — no offline workaround for a permission denial.
"""
from __future__ import annotations

from typing import Iterable

from apps.farms.models import StaffMembership

WRITE_ANY_ROLES = {StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER}
WRITE_OWN_ROLES = WRITE_ANY_ROLES | {StaffMembership.ROLE_FIELD}


def role_for(user, tenant_id) -> str | None:
    if not user or not getattr(user, "is_authenticated", False) or tenant_id is None:
        return None
    membership = (
        StaffMembership.objects.filter(user=user, farm_id=tenant_id)
        .only("role")
        .first()
    )
    return membership.role if membership else None


def can_read(role: str | None) -> bool:
    return role is not None  # any membership reads


def can_create(role: str | None, *, table: str) -> bool:
    if role is None:
        return False
    if role == StaffMembership.ROLE_VIEWER:
        return False
    if table in {
        "farms_farm",
        "farms_staffmembership",
        "enterprises_enterprise",
        "finance_account",  # structural; owners + managers only
    }:
        return role in WRITE_ANY_ROLES
    return role in WRITE_OWN_ROLES


def can_modify_instance(role: str | None, *, instance, user, table: str) -> bool:
    """For update/delete. instance is the row being changed (may be None for
    pre-flight checks). user is the request user; needed to evaluate the
    write-own rule.
    """
    if role is None:
        return False
    if role == StaffMembership.ROLE_VIEWER:
        return False
    if role in WRITE_ANY_ROLES:
        return True
    # Field staff: only activities they recorded OR performed, never
    # farms/enterprises/staff. Allows a manager to record on behalf of a
    # field-staff member and still have that staff member edit it later.
    if table == "activities_activity" and instance is not None:
        uid = getattr(user, "id", None)
        return (
            getattr(instance, "actor_user_id", None) == uid
            or getattr(instance, "performed_by_id", None) == uid
        )
    return False


def assert_can_modify(role: str | None, *, instance, user, table: str) -> None:
    if not can_modify_instance(role=role, instance=instance, user=user, table=table):
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        raise DRFPermissionDenied(_explain(role, table))


def assert_can_create(role: str | None, table: str) -> None:
    if not can_create(role, table=table):
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        raise DRFPermissionDenied(_explain(role, table))


def _explain(role: str | None, table: str) -> str:
    if role is None:
        return "You don't have access to this farm."
    if role == StaffMembership.ROLE_VIEWER:
        return "Viewers can read but not edit records."
    if role == StaffMembership.ROLE_FIELD:
        if table == "activities_activity":
            return "Field staff can only edit activities they themselves recorded."
        return "Field staff can only record activities — ask an owner or manager."
    return "Not allowed."


def all_write_roles() -> Iterable[str]:
    return WRITE_OWN_ROLES
