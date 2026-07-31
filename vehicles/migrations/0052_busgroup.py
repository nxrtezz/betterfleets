from django.db import migrations, models
import django.db.models.deletion
from django.db.models.functions import Upper

import busstops.fields
import vehicles.fields


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0051_vehiclerevision_garage_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(db_index=True, max_length=255, unique=True)),
                ("slug", busstops.fields.AutoSlugField(editable=True, populate_from="title", unique=True)),
                ("description", models.TextField(blank=True)),
                ("header_background", vehicles.fields.ColourField(blank=True, max_length=7)),
                ("header_foreground", vehicles.fields.ColourField(blank=True, max_length=7)),
                ("accent_colour", vehicles.fields.ColourField(blank=True, max_length=7)),
                ("banner", models.ImageField(blank=True, null=True, upload_to="bus-groups/banners")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                ("vehicles", models.ManyToManyField(blank=True, related_name="bus_groups", to="vehicles.vehicle")),
            ],
            options={
                "verbose_name": "bus group",
                "verbose_name_plural": "bus groups",
                "ordering": ("title",),
            },
        ),
        migrations.AddConstraint(
            model_name="busgroup",
            constraint=models.UniqueConstraint(
                Upper("title"),
                name="vehicles_bus_group_unique_title_upper",
            ),
        ),
    ]
