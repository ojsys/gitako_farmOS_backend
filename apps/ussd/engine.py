"""USSD session engine (PRD M19).

Feature-phone access for the lowest-end users: log core activities, check
balance, receive alerts — over a USSD menu. Telco gateways (Africa's Talking,
Termii, etc.) POST the accumulated input string on each step and expect a reply
prefixed `CON` (continue, more input) or `END` (terminate).

This engine is gateway-agnostic: `process(phone, text)` takes the raw input
string ("1*2") and returns (reply, should_continue). The view adapts whatever
gateway calls it. No persistent session store needed — the full text string is
replayed each step, so the menu is derived from it (standard USSD pattern).
"""
from __future__ import annotations

from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.enterprises.models import Enterprise
from apps.farms.models import StaffMembership
from apps.finance.models import Transaction
from apps.notifications.models import Notification


def _naira(kobo: int) -> str:
    return f"N{kobo / 100:,.0f}"


def _user_for(phone: str) -> User | None:
    return User.objects.filter(phone=phone).first()


def _primary_farm(user):
    membership = StaffMembership.objects.filter(user=user).select_related("farm").first()
    return membership.farm if membership else None


def process(phone: str, text: str) -> tuple[str, bool]:
    """Return (message, should_continue). message is sent without the CON/END
    prefix; the view adds it from should_continue."""
    user = _user_for(phone)
    if user is None:
        return ("Number not registered with Gitako. Download the app to get started.", False)
    farm = _primary_farm(user)
    if farm is None:
        return ("No farm linked to this number yet. Set one up in the Gitako app.", False)

    parts = [p for p in (text or "").split("*") if p != ""]

    # Top-level menu
    if not parts:
        return (
            "Gitako\n1. Today's cash balance\n2. My alerts\n3. Log an activity",
            True,
        )

    choice = parts[0]
    if choice == "1":
        return (_balance(farm), False)
    if choice == "2":
        return (_alerts(user), False)
    if choice == "3":
        return _log_activity_flow(user, farm, parts[1:])
    return ("Invalid choice. Dial again.", False)


def _balance(farm) -> str:
    txns = Transaction.objects.filter(tenant_id=farm.id, deleted_at__isnull=True)
    total = txns.aggregate(s=Sum("amount_kobo"))["s"] or 0
    return f"{farm.name}\nNet position: {_naira(total)}"


def _alerts(user) -> str:
    unread = Notification.objects.filter(user=user, is_read=False).order_by("-created_at")[:3]
    if not unread:
        return "No new alerts."
    lines = [f"- {n.title}" for n in unread]
    return "Your alerts:\n" + "\n".join(lines)


def _log_activity_flow(user, farm, rest: list[str]) -> tuple[str, bool]:
    """3 → pick enterprise → pick activity type → confirm.

    rest is the input after the top-level '3':
      []            → list enterprises
      [ent_idx]     → list activity types
      [ent_idx, ty] → record + confirm
    """
    enterprises = list(
        Enterprise.objects.filter(farm=farm, deleted_at__isnull=True,
                                  lifecycle_state="active")[:9]
    )
    if not enterprises:
        return ("No active enterprises to log against. Use the app to add one.", False)

    if not rest:
        menu = "\n".join(f"{i + 1}. {e.name}" for i, e in enumerate(enterprises))
        return (f"Choose enterprise:\n{menu}", True)

    try:
        ent = enterprises[int(rest[0]) - 1]
    except (ValueError, IndexError):
        return ("Invalid enterprise. Dial again.", False)

    type_options = _activity_options(ent.type)
    if len(rest) == 1:
        menu = "\n".join(f"{i + 1}. {label}" for i, (label, _) in enumerate(type_options))
        return (f"Activity for {ent.name}:\n{menu}", True)

    try:
        label, code = type_options[int(rest[1]) - 1]
    except (ValueError, IndexError):
        return ("Invalid activity. Dial again.", False)

    from apps.activities.models import Activity
    Activity.objects.create(
        tenant_id=farm.id, enterprise=ent, type=code,
        actor_user=user, performed_by=user, occurred_at=timezone.now(),
        notes="Logged via USSD",
    )
    return (f"Recorded: {label} on {ent.name}. Thank you.", False)


def _activity_options(enterprise_type: str) -> list[tuple[str, str]]:
    if enterprise_type == "crop_cycle":
        return [("Weeding", "weeding"), ("Spraying", "spraying"), ("Harvest", "harvesting")]
    if enterprise_type in ("flock", "herd", "pond"):
        return [("Feed", "feed"), ("Mortality", "mortality"), ("Sale", "sale")]
    return [("Note", "note")]
