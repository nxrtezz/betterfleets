from decimal import Decimal

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0043_vehicle_reviews_profile_fields_and_accessibility"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehiclereview",
            name="rating",
            field=models.DecimalField(
                decimal_places=1,
                max_digits=2,
                validators=[
                    django.core.validators.MinValueValidator(Decimal("0.5")),
                    django.core.validators.MaxValueValidator(Decimal("5.0")),
                ],
            ),
        ),
    ]
