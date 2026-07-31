from django.core import validators
from django.db import migrations, models

import busstops.models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0046_drop_vosa_tables"),
    ]

    operations = [
        migrations.CreateModel(
            name="PreservationGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=48, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.TextField(blank=True)),
                ("website", models.URLField(blank=True)),
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
                ("founded_date", models.DateField(blank=True, null=True)),
                (
                    "logo",
                    models.FileField(
                        blank=True,
                        help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
                        null=True,
                        upload_to="preservation-groups/logos",
                        validators=[
                            validators.FileExtensionValidator(
                                allowed_extensions=("svg", "png", "jpg", "jpeg", "webp")
                            ),
                            busstops.models.validate_logo_file_size,
                        ],
                    ),
                ),
                ("banner", models.ImageField(blank=True, null=True, upload_to="preservation-groups/banners")),
            ],
            options={
                "verbose_name": "preservation group",
                "verbose_name_plural": "preservation groups",
                "ordering": ("name",),
            },
        ),
        migrations.AlterModelOptions(
            name="organisation",
            options={
                "ordering": ("name",),
                "verbose_name": "Major Operator",
                "verbose_name_plural": "Major Operators",
            },
        ),
        migrations.AlterModelOptions(
            name="operatorgroup",
            options={
                "ordering": ("name",),
                "verbose_name": "Division",
                "verbose_name_plural": "Divisions",
            },
        ),
    ]
