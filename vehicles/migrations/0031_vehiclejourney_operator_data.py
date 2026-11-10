import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("busstops", "0030_alter_outofservicetrackingcode_operator"),
        ("vehicles", "0030_vehiclerevision_from_garage_vehiclerevision_to_garage"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclejourney",
            name="operator",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                help_text="operator for journeys without a vehicle (eg Darwin trains)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="busstops.operator",
            ),
        ),
        migrations.AddField(
            model_name="vehiclejourney",
            name="data",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
