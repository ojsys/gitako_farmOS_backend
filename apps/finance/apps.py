from django.apps import AppConfig


class FinanceConfig(AppConfig):
    name = "apps.finance"
    label = "finance"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Importing connects the @receiver decorators.
        from . import signals  # noqa: F401
