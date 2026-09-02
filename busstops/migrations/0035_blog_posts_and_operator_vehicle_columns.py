import busstops.fields
from django.db import migrations, models
from django.db.models.functions import Upper


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0033_stopfeature_stoppoint_features"),
    ]

    operations = [
        migrations.CreateModel(
            name="BlogTag",
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
                ("name", models.CharField(max_length=60, unique=True)),
                (
                    "slug",
                    busstops.fields.AutoSlugField(
                        editable=True,
                        populate_from="name",
                        unique=True,
                    ),
                ),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="BlogPost",
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
                ("title", models.CharField(max_length=160)),
                (
                    "slug",
                    busstops.fields.AutoSlugField(
                        editable=True,
                        populate_from="title",
                        unique=True,
                    ),
                ),
                ("excerpt", models.TextField(blank=True)),
                ("body", models.TextField()),
                ("published", models.BooleanField(default=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tags",
                    models.ManyToManyField(
                        blank=True,
                        related_name="posts",
                        to="busstops.blogtag",
                    ),
                ),
            ],
            options={
                "ordering": ("-published_at", "-created_at"),
            },
        ),
        migrations.CreateModel(
            name="OperatorVehicleColumn",
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
                ("name", models.CharField(max_length=80)),
                (
                    "slug",
                    busstops.fields.AutoSlugField(
                        editable=True,
                        populate_from="name",
                    ),
                ),
                ("help_text", models.CharField(blank=True, max_length=255)),
                ("display_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "operator",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="vehicle_columns",
                        to="busstops.operator",
                    ),
                ),
            ],
            options={
                "ordering": ("display_order", "name"),
            },
        ),
        migrations.AddConstraint(
            model_name="operatorvehiclecolumn",
            constraint=models.UniqueConstraint(
                Upper("name"),
                "operator",
                name="busstops_operator_vehicle_column_unique_name_per_operator",
            ),
        ),
        migrations.AddConstraint(
            model_name="operatorvehiclecolumn",
            constraint=models.UniqueConstraint(
                "operator",
                "slug",
                name="busstops_operator_vehicle_column_unique_slug_per_operator",
            ),
        ),
    ]
