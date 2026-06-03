"""Register the notification beat schedules in django-celery-beat.

Idempotent — safe to run on every deploy. The DatabaseScheduler reads schedules
from the DB, so code-defined `beat_schedule` wouldn't take effect; this command
is the supported way to declare them.

Cadence:
  - calendar reminders : daily at 06:00 (local)
  - threshold alerts   : hourly (mortality / low-stock / overdue)
  - daily digest       : hourly at :05 (the engine filters by each user's hour)
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create/refresh the notification PeriodicTask schedules."

    def handle(self, *args, **options):
        from django_celery_beat.models import CrontabSchedule, PeriodicTask

        daily_6am, _ = CrontabSchedule.objects.get_or_create(
            minute="0", hour="6", day_of_week="*", day_of_month="*", month_of_year="*",
        )
        hourly, _ = CrontabSchedule.objects.get_or_create(
            minute="0", hour="*", day_of_week="*", day_of_month="*", month_of_year="*",
        )
        hourly_5, _ = CrontabSchedule.objects.get_or_create(
            minute="5", hour="*", day_of_week="*", day_of_month="*", month_of_year="*",
        )

        specs = [
            ("notifications: calendar reminders", "notifications.fire_calendar_reminders", daily_6am),
            ("notifications: threshold alerts", "notifications.evaluate_thresholds", hourly),
            ("notifications: daily digest", "notifications.send_daily_digest", hourly_5),
        ]

        for name, task, schedule in specs:
            obj, created = PeriodicTask.objects.update_or_create(
                name=name,
                defaults={"task": task, "crontab": schedule, "enabled": True},
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{verb}: {name} → {task}"))
