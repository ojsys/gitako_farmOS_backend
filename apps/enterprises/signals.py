"""Close the plan→do→track loop: when a farm hand logs an activity, mark the
matching SeasonTask done.

Works for activities created via REST or the offline sync pipeline alike, since
both end in an Activity.save(). Wired in apps/enterprises/apps.py.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.activities.models import Activity

from .season_tasks import complete_task_from_activity

log = logging.getLogger("gitako.enterprises")


@receiver(post_save, sender=Activity)
def complete_season_task_for_activity(sender, instance: Activity, created: bool, **kwargs):
    if not created or instance.deleted_at is not None:
        return
    try:
        task = complete_task_from_activity(instance)
        if task is not None:
            log.info("Activity %s completed SeasonTask %s", instance.id, task.id)
    except Exception:  # noqa: BLE001 — never let task-matching break activity logging
        log.exception("Failed to auto-complete SeasonTask for activity %s", instance.id)
