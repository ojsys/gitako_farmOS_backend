"""Context processor: populate dashboard data for the custom admin index."""
from __future__ import annotations


def admin_kpis(request) -> dict:
    if not request.path.startswith("/admin/") or not getattr(request.user, "is_staff", False):
        return {}
    try:
        from apps.accounts.models import User
        from apps.activities.models import Activity
        from apps.enterprises.models import Enterprise
        from apps.farms.models import Farm
        from apps.sync.models import ChangeLog
    except Exception:  # noqa: BLE001 — apps not migrated yet
        return {}

    from django.utils import timezone
    one_day_ago = timezone.now() - timezone.timedelta(days=1)

    return {
        "gitako_kpis": [
            {"label": "Farms", "value": Farm.objects.filter(deleted_at__isnull=True).count(),
             "hint": "Live farms in scope"},
            {"label": "Enterprises", "value": Enterprise.objects.filter(deleted_at__isnull=True).count(),
             "hint": "Across all farms"},
            {"label": "Activities · today",
             "value": Activity.objects.filter(occurred_at__gte=one_day_ago).count(),
             "hint": "Logged in the last 24h"},
            {"label": "Users", "value": User.objects.filter(is_active=True).count(),
             "hint": "Active accounts"},
            {"label": "Sync ops · 24h",
             "value": ChangeLog.objects.filter(at__gte=one_day_ago).count(),
             "hint": "ChangeLog rows"},
        ],
        "gitako_recent_farms": _recent_farms(),
        "gitako_pending_activities": _pending_activities(),
        "gitako_recent_changes": _recent_changes(),
    }


def _recent_farms():
    from apps.farms.models import Farm
    rows = []
    for f in (
        Farm.objects.filter(deleted_at__isnull=True)
        .select_related("owner").order_by("-created_at")[:6]
    ):
        rows.append({
            "id": f.id,
            "name": f.name,
            "region": f.region,
            "owner_label": (
                (f.owner.full_name if f.owner else "")
                or (f.owner.phone if f.owner else "—")
            ),
            "staff_count": f.memberships.count(),
            "created_at": f.created_at,
        })
    return rows


def _pending_activities():
    from apps.activities.models import Activity
    rows = []
    for a in (
        Activity.objects.filter(approved_at__isnull=True, deleted_at__isnull=True)
        .select_related("enterprise", "actor_user")
        .order_by("-occurred_at")[:6]
    ):
        rows.append({
            "id": a.id,
            "type_label": a.type.replace("_", " ").title(),
            "enterprise_name": a.enterprise.name if a.enterprise_id else "—",
            "actor_label": (
                (a.actor_user.full_name if a.actor_user_id else "")
                or (a.actor_user.phone if a.actor_user_id else "system")
            ),
            "occurred_at": a.occurred_at,
        })
    return rows


def _recent_changes():
    from apps.sync.models import ChangeLog
    rows = []
    for c in ChangeLog.objects.order_by("-at")[:8]:
        rows.append({
            "op": c.op,
            "table": c.table,
            "row_short": str(c.row_id)[:8] + "…",
            "at": c.at,
        })
    return rows
