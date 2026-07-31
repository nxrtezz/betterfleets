from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0043_vehicle_reviews_profile_fields_and_accessibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="historical_fleet_creator",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
