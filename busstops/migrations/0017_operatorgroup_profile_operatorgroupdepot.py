import django.contrib.gis.db.models.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0016_organisation_operatorgroup_organisation"),
    ]

    operations = [
        migrations.AddField(
            model_name="operatorgroup",
            name="accent_colour",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="banner",
            field=models.ImageField(blank=True, null=True, upload_to="operator-groups/banners"),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="custom_css",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="header_background",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="header_foreground",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="operator-groups/logos"),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_fb",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_instagram",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_other",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="social_x",
            field=models.URLField(blank=True),
        ),
        migrations.AddField(
            model_name="operatorgroup",
            name="website",
            field=models.URLField(blank=True),
        ),
        migrations.CreateModel(
            name="OperatorGroupDepot",
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
                ("name", models.CharField(max_length=100)),
                (
                    "location",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, null=True, srid=4326
                    ),
                ),
                ("address", models.CharField(blank=True, max_length=255)),
                ("notes", models.CharField(blank=True, max_length=255)),
                (
                    "group",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="busstops.operatorgroup"),
                ),
            ],
            options={"ordering": ("name",)},
        ),
    ]
