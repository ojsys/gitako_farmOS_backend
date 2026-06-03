"""Run notification jobs synchronously — for hosts without Celery/Redis.

On shared cPanel there's no long-running Celery worker or beat scheduler, so the
periodic notification jobs are driven by **cron** calling this command instead.

Examples (cPanel → Cron Jobs), using the app's virtualenv python:
    # every 30 min — due GAP-task reminders
    */30 * * * *  /home/USER/virtualenv/.../bin/python /home/USER/gitako/backend/manage.py run_notification_jobs --job reminders
    # hourly — threshold/health alerts (mortality, FCR, low stock…)
    0 * * * *     ... manage.py run_notification_jobs --job thresholds
    # once a day at 6am — daily digest
    0 6 * * *     ... manage.py run_notification_jobs --job digest

Or run them all at once:  manage.py run_notification_jobs
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.notifications import engine

JOBS = {
    "reminders": ("Calendar reminders", engine.run_calendar_reminders),
    "thresholds": ("Threshold alerts", engine.run_threshold_alerts),
    "digest": ("Daily digest", engine.run_daily_digest),
}


class Command(BaseCommand):
    help = "Run notification jobs synchronously (cron-friendly; no Celery needed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            choices=list(JOBS.keys()) + ["all"],
            default="all",
            help="Which job to run (default: all).",
        )

    def handle(self, *args, **opts):
        which = opts["job"]
        keys = list(JOBS.keys()) if which == "all" else [which]
        for key in keys:
            label, fn = JOBS[key]
            try:
                count = fn()
                self.stdout.write(self.style.SUCCESS(f"{label}: {count} notification(s) sent"))
            except Exception as exc:  # noqa: BLE001 — cron should keep going
                self.stderr.write(self.style.ERROR(f"{label} failed: {exc}"))
