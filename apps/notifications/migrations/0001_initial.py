import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("farms", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DigestPreference",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("enabled", models.BooleanField(default=True)),
                ("send_hour", models.PositiveSmallIntegerField(default=18)),
                ("last_sent_on", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="digest_preference", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="NotificationRule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("rule_type", models.CharField(choices=[("mortality_spike", "Mortality spike"), ("low_stock", "Low stock"), ("overdue_activity", "Overdue activity")], max_length=32)),
                ("enabled", models.BooleanField(default=True)),
                ("params", models.JSONField(blank=True, default=dict)),
                ("channels", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("farm", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notification_rules", to="farms.farm")),
            ],
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("type", models.CharField(choices=[("calendar_reminder", "Calendar reminder"), ("mortality_spike", "Mortality spike"), ("low_stock", "Low stock"), ("overdue_activity", "Overdue activity"), ("daily_digest", "Daily digest"), ("custom", "Custom")], default="custom", max_length=32)),
                ("title", models.CharField(max_length=160)),
                ("body", models.TextField(blank=True)),
                ("data", models.JSONField(blank=True, default=dict)),
                ("dedupe_key", models.CharField(max_length=200)),
                ("channels_sent", models.JSONField(blank=True, default=list)),
                ("is_read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="notificationrule",
            constraint=models.UniqueConstraint(fields=("farm", "rule_type"), name="uniq_rule_per_farm"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "is_read", "-created_at"], name="notificatio_user_id_4f8d2b_idx"),
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(fields=("user", "dedupe_key"), name="uniq_notification_dedupe"),
        ),
    ]
