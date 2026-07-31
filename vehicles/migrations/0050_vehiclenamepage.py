import busstops.fields
from django.db import migrations, models
from django.db.models.functions import Upper


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0049_vehicle_review_delete_permission"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleNamePage",
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
                ("name", models.CharField(db_index=True, max_length=255, unique=True)),
                (
                    "slug",
                    busstops.fields.AutoSlugField(
                        editable=True,
                        populate_from="name",
                        unique=True,
                    ),
                ),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "vehicle name page",
                "verbose_name_plural": "vehicle name pages",
                "ordering": ("name",),
            },
        ),
        migrations.AddConstraint(
            model_name="vehiclenamepage",
            constraint=models.UniqueConstraint(
                Upper("name"),
                name="vehicles_vehicle_name_page_unique_name_upper",
            ),
        ),
    ]
