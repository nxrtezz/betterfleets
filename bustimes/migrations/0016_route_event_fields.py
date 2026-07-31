from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bustimes", "0015_garage_location_backfill"),
    ]

    operations = [
        migrations.AddField(
            model_name="route",
            name="event_end_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="route",
            name="event_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="route",
            name="event_visibility_weeks",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
