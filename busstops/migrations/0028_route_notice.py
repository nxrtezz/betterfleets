from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0027_bustimes_sync_state_stop_groups"),
    ]

    # This migration creates the RouteNotice model
    # Originally there was a duplicate 0028_routenotice.py which has been removed

    operations = [
        migrations.CreateModel(
            name="RouteNotice",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=120)),
                ("description", models.TextField()),
                ("start", models.DateField()),
                ("end", models.DateField()),
                ("planned", models.BooleanField(default=False)),
                ("diversion", models.BooleanField(default=False)),
                ("diversion_num", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("route_map_id", models.CharField(blank=True, editable=False, max_length=80)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="route_notices",
                        to="busstops.service",
                    ),
                ),
                (
                    "other_services",
                    models.ManyToManyField(
                        blank=True,
                        related_name="related_route_notices",
                        to="busstops.service",
                    ),
                ),
            ],
            options={
                "ordering": ("-start", "-end", "title"),
            },
        ),
        migrations.AddConstraint(
            model_name="routenotice",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("diversion", False), ("diversion_num__isnull", False), _connector="OR"
                ),
                name="route_notice_diversion_num_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="routenotice",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("diversion_num__isnull", True), ("diversion_num__lte", 9999), _connector="OR"
                ),
                name="route_notice_diversion_num_0000_9999",
            ),
        ),
    ]
