from django.apps import AppConfig


class FleetConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "fleet"
    verbose_name = "Fleet imports"

    def ready(self):
        from . import signals  # noqa: F401
