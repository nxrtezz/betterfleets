from django.apps import AppConfig


class VehicleHistoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "vehicle_history"
    verbose_name = "Vehicle History"

    def ready(self):
        import vehicle_history.signals
