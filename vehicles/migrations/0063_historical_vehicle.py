# Generated manually for HistoricalVehicle model

import django.db.models.deletion
from django.db import migrations, models

import busstops.fields
from vehicles.fields import ColourField, ColoursField, CSSField


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0026_operator_fleet_list_notes"),
        ("vehicles", "0062_remove_historicallivery_history_user_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalVehicle",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("slug", busstops.fields.AutoSlugField(editable=True, populate_from="vehicle_slug", unique=True)),
                ("code", models.CharField(max_length=255)),
                ("fleet_number", models.PositiveIntegerField(blank=True, null=True)),
                ("fleet_code", models.CharField(blank=True, max_length=24)),
                ("reg", models.CharField(blank=True, max_length=24)),
                ("prev_registration", models.CharField(blank=True, max_length=24)),
                ("colours", ColoursField(blank=True, max_length=255)),
                ("name", models.CharField(blank=True, max_length=255)),
                ("branding", models.CharField(blank=True, max_length=255)),
                ("rear_advert", models.CharField(blank=True, max_length=255)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("fleet_support_vehicle", models.BooleanField(default=False)),
                ("trainer_vehicle", models.BooleanField(default=False)),
                ("year_of_manufacture", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "joined_fleet_date",
                    models.DateField(
                        blank=True,
                        help_text="Date the vehicle joined the fleet (dd-mm-yyyy)",
                        null=True,
                    ),
                ),
                (
                    "left_fleet_date",
                    models.DateField(
                        blank=True,
                        help_text="Date the vehicle left the fleet (dd-mm-yyyy)",
                        null=True,
                    ),
                ),
                (
                    "previous_operators",
                    models.JSONField(
                        blank=True,
                        help_text="List of previous operators with joined_fleet dates. Format: [{'operator_id': 123, 'joined_fleet': '01-2024'}]",
                        null=True,
                    ),
                ),
                ("data", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "operator",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="busstops.operator",
                    ),
                ),
                (
                    "operated_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="Operator that operates this vehicle (if different from the owner)",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="operated_historical_vehicles",
                        to="busstops.operator",
                    ),
                ),
                (
                    "vehicle_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="vehicles.vehicletype",
                    ),
                ),
                (
                    "livery",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="vehicles.livery",
                    ),
                ),
                (
                    "garage",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="bustimes.garage",
                    ),
                ),
            ],
            options={
                "app_label": "vehicles",
                "ordering": ("fleet_number", "fleet_code", "reg", "id"),
                "indexes": [
                    models.Index(fields=["fleet_code"], name="historical_fleet_code"),
                    models.Index(fields=["reg"], name="historical_reg"),
                ],
            },
        ),
        migrations.AddField(
            model_name="historicalvehicle",
            name="features",
            field=models.ManyToManyField(
                blank=True, to="vehicles.vehiclefeature"
            ),
        ),
    ]
