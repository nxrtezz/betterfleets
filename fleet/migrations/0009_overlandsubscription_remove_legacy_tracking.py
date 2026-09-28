import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fleet", "0008_merge_0002_pinnedoperator_0007_fleetphotolog_quantity"),
        ("vehicles", "0001_squashed_0003_sirisubscription"),
    ]

    operations = [
        migrations.CreateModel(
            name="OverlandSubscription",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("destination", models.CharField(blank=True, max_length=255)),
                ("route_number", models.CharField(blank=True, max_length=64)),
                ("trip_id", models.CharField(blank=True, max_length=128)),
                ("auth_key_hash", models.CharField(max_length=64)),
                ("latitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("longitude", models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ("heading", models.IntegerField(blank=True, null=True)),
                ("last_timestamp", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="overland_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "vehicle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="overland_subscriptions",
                        to="vehicles.vehicle",
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at",),
                "permissions": [
                    ("use_overland", "Can generate Overland tracking URLs"),
                ],
            },
        ),
        migrations.DeleteModel(name="LiveVehicleLocation"),
    ]
