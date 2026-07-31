from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0038_vehicle_historical_fleet_year"),
    ]

    operations = [
        migrations.AddField(
            model_name="livery",
            name="description",
            field=models.TextField(blank=True),
        ),
    ]
