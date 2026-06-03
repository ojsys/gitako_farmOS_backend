"""Celery task wrappers around the notification engine.

Schedules are registered in the DB (django-celery-beat DatabaseScheduler) via the
`seed_periodic_tasks` management command — see that command for the cadence.
"""
from __future__ import annotations

from celery import shared_task

from . import engine


@shared_task(name="notifications.fire_calendar_reminders")
def fire_calendar_reminders() -> int:
    return engine.run_calendar_reminders()


@shared_task(name="notifications.evaluate_thresholds")
def evaluate_thresholds() -> int:
    return engine.run_threshold_alerts()


@shared_task(name="notifications.send_daily_digest")
def send_daily_digest() -> int:
    return engine.run_daily_digest()
