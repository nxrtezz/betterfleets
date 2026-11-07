import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bustimes", "0028_garage_id"),
        ("vehicles", "0029_vehiclerevision_vehicle_nullable_and_is_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclerevision",
            name="from_garage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revision_from_garage",
                to="bustimes.garage",
            ),
        ),
        migrations.AddField(
            model_name="vehiclerevision",
            name="to_garage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revision_to_garage",
                to="bustimes.garage",
            ),
        ),
    ]
