from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0037_vehicle_demonstrator"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="historical_fleet_year",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
