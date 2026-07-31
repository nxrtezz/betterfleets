from django.apps import AppConfig


class BusstopsConfig(AppConfig):
    name = "busstops"

    def ready(self):
        from . import vehicle_revision_signals  # noqa: F401
