"""Notification dispatch — the one entry point the schedulers call.

`notify()` creates an in-app Notification idempotently on (user, dedupe_key),
then fans out to the other requested channels. Repeated scheduler runs with the
same dedupe_key are no-ops (the row already exists), so cron cadence never spams
a user.

Channels in v1: **in-app** (always) and **SMS** (critical alerts only). There is
no push provider — clients surface new notifications by polling the in-app feed
(see the web bell and the mobile inbox). A WhatsApp channel can slot in here
later as another branch, exactly like SMS.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from apps.accounts.sms import get_provider as get_sms_provider
from apps.farms.models import StaffMembership

from .models import Notification

log = logging.getLogger("gitako.notifications")

CHANNEL_IN_APP = "in_app"
CHANNEL_SMS = "sms"
DEFAULT_CHANNELS = (CHANNEL_IN_APP,)


@dataclass
class NotifyResult:
    notification: Notification | None
    created: bool
    channels_sent: list[str] = field(default_factory=list)


def farm_alert_recipients(farm) -> list:
    """Users who should receive operational alerts for a farm: owners + managers."""
    memberships = StaffMembership.objects.filter(
        farm=farm, role__in=[StaffMembership.ROLE_OWNER, StaffMembership.ROLE_MANAGER],
    ).select_related("user")
    return [m.user for m in memberships]


def notify(
    *,
    user,
    type: str,
    title: str,
    body: str = "",
    dedupe_key: str,
    tenant_id=None,
    data: dict | None = None,
    channels: tuple[str, ...] | list[str] = DEFAULT_CHANNELS,
) -> NotifyResult:
    """Create + dispatch one notification idempotently. Safe to call repeatedly."""
    data = data or {}

    # Idempotent insert on (user, dedupe_key).
    try:
        with transaction.atomic():
            notification, created = Notification.objects.get_or_create(
                user=user,
                dedupe_key=dedupe_key,
                defaults={
                    "type": type,
                    "title": title,
                    "body": body,
                    "data": data,
                    "tenant_id": tenant_id,
                    "channels_sent": [CHANNEL_IN_APP],
                },
            )
    except IntegrityError:
        # Lost a race — the row exists, treat as already-sent.
        notification = Notification.objects.get(user=user, dedupe_key=dedupe_key)
        created = False

    if not created:
        return NotifyResult(notification=notification, created=False)

    sent = [CHANNEL_IN_APP]

    if CHANNEL_SMS in channels and getattr(user, "phone", ""):
        try:
            get_sms_provider().send(phone=user.phone, message=f"{title}. {body}".strip())
            sent.append(CHANNEL_SMS)
        except Exception as exc:  # noqa: BLE001
            log.warning("sms dispatch failed: %s", exc)

    if sent != notification.channels_sent:
        notification.channels_sent = sent
        notification.save(update_fields=["channels_sent"])

    return NotifyResult(notification=notification, created=True, channels_sent=sent)
