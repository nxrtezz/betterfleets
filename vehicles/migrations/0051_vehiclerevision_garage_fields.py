from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("bustimes", "0016_route_event_fields"),
        ("vehicles", "0050_vehiclenamepage"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclerevision",
            name="from_garage",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revision_from",
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
                related_name="revision_to",
                to="bustimes.garage",
            ),
        ),
        migrations.AddConstraint(
            model_name="vehiclerevision",
            constraint=models.UniqueConstraint(
                condition=models.Q(("pending", True)),
                fields=("vehicle", "to_garage"),
                name="unique_pending_garage",
            ),
        ),
    ]
