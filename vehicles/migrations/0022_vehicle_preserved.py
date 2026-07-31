from django.db import migrations, models
import django.db.models
import django.db.models.functions.text


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0021_vehicle_historical_fleet"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="preserved",
            field=models.BooleanField(
                default=False,
                help_text="Keep this vehicle as a preserved record outside the active fleet list.",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="vehicle",
            name="vehicle_operator_and_code",
        ),
        migrations.AddConstraint(
            model_name="vehicle",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Upper("code"),
                models.F("operator"),
                condition=django.db.models.Q(
                    historical_fleet__isnull=True,
                    preserved=False,
                ),
                name="vehicle_operator_and_code_live",
            ),
        ),
    ]
