from django.contrib.gis.db import models as gis_models
from django.db import migrations, models
import django.db.models.deletion

import busstops.fields


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0026_operator_fleet_list_notes"),
    ]

    operations = [
        migrations.CreateModel(
            name="BustimesSyncState",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_type", models.CharField(max_length=50)),
                ("external_id", models.CharField(max_length=100)),
                ("local_model", models.CharField(blank=True, max_length=100)),
                ("local_pk", models.CharField(blank=True, max_length=100)),
                ("last_fields", models.JSONField(blank=True, default=dict)),
                ("last_payload", models.JSONField(blank=True, default=dict)),
                ("protected_fields", models.JSONField(blank=True, default=list)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "unique_together": {("object_type", "external_id")},
            },
        ),
        migrations.CreateModel(
            name="StopGroup",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", busstops.fields.AutoSlugField(editable=True, max_length=50, populate_from="name", unique=True)),
                ("location", gis_models.PointField(blank=True, null=True, srid=4326)),
                ("active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="StopGroupStop",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveSmallIntegerField(default=0)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="busstops.stopgroup")),
                ("stop", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="busstops.stoppoint")),
            ],
            options={
                "ordering": ("order", "stop__common_name", "stop__indicator"),
                "unique_together": {("group", "stop")},
            },
        ),
        migrations.AddField(
            model_name="stopgroup",
            name="stops",
            field=models.ManyToManyField(blank=True, through="busstops.StopGroupStop", to="busstops.stoppoint"),
        ),
        migrations.AddIndex(
            model_name="bustimessyncstate",
            index=models.Index(fields=["object_type", "external_id"], name="busstops_bu_object__7259f3_idx"),
        ),
        migrations.AddIndex(
            model_name="bustimessyncstate",
            index=models.Index(fields=["local_model", "local_pk"], name="busstops_bu_local_m_90aab3_idx"),
        ),
    ]
