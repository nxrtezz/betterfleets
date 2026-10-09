# Generated for primary and secondary logo fields on Service model

from django.db import migrations, models
import busstops.fields
import busstops.models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0066_datachangelog_permissions"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="primary_logo",
            field=models.FileField(
                blank=True,
                help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
                null=True,
                upload_to="services/primary-logos",
                validators=busstops.models.logo_file_validators,
            ),
        ),
        migrations.AddField(
            model_name="service",
            name="secondary_logo",
            field=models.FileField(
                blank=True,
                help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
                null=True,
                upload_to="services/secondary-logos",
                validators=busstops.models.logo_file_validators,
            ),
        ),
    ]
