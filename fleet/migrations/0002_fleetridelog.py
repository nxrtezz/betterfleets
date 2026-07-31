from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("vehicles", "0051_vehiclerevision_garage_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="FleetRideLog",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="fleet_ride_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "vehicle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ride_logs",
                        to="vehicles.vehicle",
                    ),
                ),
            ],
            options={
                "verbose_name": "fleet ride log",
                "verbose_name_plural": "fleet ride logs",
                "ordering": ("-created_at", "-id"),
                "permissions": [("use_beta_features", "Beta Features")],
            },
        ),
        migrations.AddConstraint(
            model_name="fleetridelog",
            constraint=models.UniqueConstraint(
                fields=("user", "vehicle"),
                name="fleet_unique_user_vehicle_ride_log",
            ),
        ),
    ]
