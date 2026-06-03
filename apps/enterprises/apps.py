from django.apps import AppConfig


class EnterprisesConfig(AppConfig):
    name = "apps.enterprises"
    label = "enterprises"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Importing connects the @receiver decorators.
        from . import signals  # noqa: F401
