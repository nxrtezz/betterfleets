import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0057_merge_20260606_2129"),
        ("vehicles", "0055_preservation_ownership"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="operator",
            name="user_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("owns", "owns"),
                    ("runs", "runs"),
                    ("manages", "manages"),
                    ("represents", "represents"),
                ],
                help_text="How this user relates to the operator or group (shown on the public page).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="preservationgroup",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="preservationgroup",
            name="user_role",
            field=models.CharField(
                blank=True,
                choices=[
                    ("owns", "owns"),
                    ("runs", "runs"),
                    ("manages", "manages"),
                    ("represents", "represents"),
                ],
                help_text="How this user relates to the operator or group (shown on the public page).",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="Event",
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
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("location", models.CharField(blank=True, max_length=255)),
                ("website", models.URLField(blank=True)),
                (
                    "operator",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="events",
                        to="busstops.operator",
                    ),
                ),
                (
                    "preservation_group",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="events",
                        to="busstops.preservationgroup",
                    ),
                ),
                (
                    "vehicles",
                    models.ManyToManyField(
                        blank=True,
                        related_name="events",
                        to="vehicles.vehicle",
                    ),
                ),
            ],
            options={
                "ordering": ("-start_date", "name"),
            },
        ),
        migrations.AddConstraint(
            model_name="event",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("operator__isnull", False),
                    ("preservation_group__isnull", False),
                    _connector="OR",
                ),
                name="event_requires_operator_or_preservation_group",
            ),
        ),
    ]
