from django.db import migrations, models
import django.contrib.gis.db.models.fields


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0029_datachangelog"),
    ]

    operations = [
        migrations.CreateModel(
            name="Manufacturer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=48, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("legal_name", models.CharField(blank=True, max_length=255)),
                ("short_name", models.CharField(blank=True, max_length=100)),
                ("slogan", models.CharField(blank=True, max_length=255)),
                ("description", models.TextField(blank=True)),
                ("logo", models.ImageField(blank=True, null=True, upload_to="manufacturers/logos")),
                ("banner", models.ImageField(blank=True, null=True, upload_to="manufacturers/banners")),
                ("website", models.URLField(blank=True)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("phone", models.CharField(blank=True, max_length=100)),
                ("social_x", models.URLField(blank=True)),
                ("social_fb", models.URLField(blank=True)),
                ("social_instagram", models.URLField(blank=True)),
                ("social_linkedin", models.URLField(blank=True)),
                ("social_youtube", models.URLField(blank=True)),
                ("social_tiktok", models.URLField(blank=True)),
                ("social_threads", models.URLField(blank=True)),
                ("social_bluesky", models.URLField(blank=True)),
                ("social_mastodon", models.URLField(blank=True)),
                ("social_other", models.URLField(blank=True)),
                ("header_background", models.CharField(blank=True, max_length=20)),
                ("header_foreground", models.CharField(blank=True, max_length=20)),
                ("accent_colour", models.CharField(blank=True, max_length=20)),
                ("card_background", models.CharField(blank=True, max_length=20)),
                ("button_background", models.CharField(blank=True, max_length=20)),
                ("button_foreground", models.CharField(blank=True, max_length=20)),
                ("custom_css", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "manufactor",
                "verbose_name_plural": "manufactors",
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="ManufacturerSite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("site_type", models.CharField(choices=[("factory", "factory"), ("head-office", "head office"), ("proving-ground", "proving ground"), ("engineering", "engineering centre"), ("sales", "sales and support"), ("other", "other")], default="factory", max_length=20)),
                ("location", django.contrib.gis.db.models.fields.PointField(blank=True, null=True, srid=4326)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("notes", models.CharField(blank=True, max_length=255)),
                ("manufacturer", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="sites", to="busstops.manufacturer")),
            ],
            options={
                "verbose_name": "manufactor site",
                "verbose_name_plural": "manufactor sites",
                "ordering": ("name",),
            },
        ),
    ]
