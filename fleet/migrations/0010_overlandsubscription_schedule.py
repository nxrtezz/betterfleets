import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bustimes", "0023_remove_simulationconfig"),
        ("fleet", "0009_overlandsubscription_remove_legacy_tracking"),
        ("vehicles", "0001_squashed_0003_sirisubscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="overlandsubscription",
            name="tracking_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="overlandsubscription",
            name="scheduled_trip",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="overland_subscriptions",
                to="bustimes.trip",
            ),
        ),
        migrations.AddField(
            model_name="overlandsubscription",
            name="journey",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="overland_subscriptions",
                to="vehicles.vehiclejourney",
            ),
        ),
    ]
