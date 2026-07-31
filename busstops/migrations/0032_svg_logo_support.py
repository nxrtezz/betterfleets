from django.core import validators
from django.db import migrations, models

import busstops.models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0031_service_non_current_route"),
    ]

    operations = [
        migrations.AlterField(
            model_name="operator",
            name="logo",
            field=models.FileField(
                blank=True,
                help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
                null=True,
                upload_to="operators",
                validators=[
                    validators.FileExtensionValidator(
                        allowed_extensions=("svg", "png", "jpg", "jpeg", "webp")
                    ),
                    busstops.models.validate_logo_file_size,
                ],
            ),
        ),
        migrations.AlterField(
            model_name="operatorgroup",
            name="logo",
            field=models.FileField(
                blank=True,
                help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
                null=True,
                upload_to="operator-groups/logos",
                validators=[
                    validators.FileExtensionValidator(
                        allowed_extensions=("svg", "png", "jpg", "jpeg", "webp")
                    ),
                    busstops.models.validate_logo_file_size,
                ],
            ),
        ),
        migrations.AlterField(
            model_name="organisation",
            name="logo",
            field=models.FileField(
                blank=True,
                help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
                null=True,
                upload_to="organisations/logos",
                validators=[
                    validators.FileExtensionValidator(
                        allowed_extensions=("svg", "png", "jpg", "jpeg", "webp")
                    ),
                    busstops.models.validate_logo_file_size,
                ],
            ),
        ),
    ]
