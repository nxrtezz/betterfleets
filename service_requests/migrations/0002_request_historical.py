# Generated migration to add missing historical table for Request model

import django.contrib.auth.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import simple_history.models


class Migration(migrations.Migration):

    dependencies = [
        ("service_requests", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalRequest",
            fields=[
                (
                    "id",
                    models.IntegerField(auto_created=True, db_index=True, verbose_name="ID"),
                ),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField()),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("vehicle", "Vehicle"),
                            ("service", "Service"),
                            ("operator", "Operator"),
                            ("vehicle_type", "Vehicle Type"),
                            ("livery", "Livery"),
                            ("site_feature", "Site Feature"),
                            ("named_page", "Named Page"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("in_progress", "In Progress"),
                            ("resolved", "Resolved"),
                            ("closed", "Closed"),
                            ("declined", "Declined"),
                        ],
                        default="open",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("fleet_number", models.CharField(blank=True, max_length=50)),
                ("registration", models.CharField(blank=True, max_length=24)),
                ("route", models.CharField(blank=True, max_length=100)),
                ("expected_behaviour", models.TextField(blank=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField()),
                ("history_change_reason", models.TextField(blank=True, null=True)),
                ("history_type", models.CharField(choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")], max_length=1)),
                ("history_user", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "livery",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="vehicles.livery",
                    ),
                ),
                (
                    "operator",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="busstops.operator",
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="busstops.service",
                    ),
                ),
                (
                    "vehicle",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="vehicles.vehicle",
                    ),
                ),
                (
                    "vehicle_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="vehicles.vehicletype",
                    ),
                ),
            ],
            options={
                "verbose_name": "historical request",
                "verbose_name_plural": "historical requests",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
