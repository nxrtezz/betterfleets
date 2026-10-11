# Generated manually for VehicleJourney vehicles ManyToMany field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0098_merge_0050_advanced_field_0097_vehicle_advanced'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiclejourney',
            name='vehicles',
            field=models.ManyToManyField(
                blank=True,
                related_name='additional_journeys',
                to='vehicles.vehicle'
            ),
        ),
        migrations.AlterField(
            model_name='vehiclejourney',
            name='vehicle',
            field=models.ForeignKey(
                db_index=False,
                null=True,
                blank=True,
                on_delete=models.CASCADE,
                related_name='journeys',
                to='vehicles.vehicle'
            ),
        ),
    ]
