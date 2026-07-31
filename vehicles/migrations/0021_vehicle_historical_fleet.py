from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0028_route_notice"),
        ("vehicles", "0020_vehiclecode_unique_vehicle_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="historical_fleet",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="historical_vehicle_set",
                to="busstops.operator",
            ),
        ),
    ]
