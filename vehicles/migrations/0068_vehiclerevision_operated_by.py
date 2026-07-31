# Generated manually for VehicleRevision operated_by fields

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0067_vehicle_operated_by'),
        ('busstops', '0026_operator_fleet_list_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiclerevision',
            name='from_operated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='revision_operated_by_from',
                to='busstops.operator',
            ),
        ),
        migrations.AddField(
            model_name='vehiclerevision',
            name='to_operated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='revision_operated_by_to',
                to='busstops.operator',
            ),
        ),
    ]
