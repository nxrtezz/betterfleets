# Generated migration for BetterFleets changes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0028_vehicle_completed'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiclerevision',
            name='is_request',
            field=models.BooleanField(default=False, help_text='True if this is a request to add a new vehicle'),
        ),
        migrations.AlterField(
            model_name='vehiclerevision',
            name='vehicle',
            field=models.ForeignKey(on_delete=models.deletion.SET_NULL, null=True, blank=True, to='vehicles.vehicle'),
        ),
        migrations.RemoveConstraint(
            model_name='vehiclerevision',
            name='unique_pending_operator',
        ),
        migrations.RemoveConstraint(
            model_name='vehiclerevision',
            name='unique_pending_type',
        ),
        migrations.RemoveConstraint(
            model_name='vehiclerevision',
            name='unique_pending_livery',
        ),
        migrations.AddConstraint(
            model_name='vehiclerevision',
            constraint=models.UniqueConstraint(
                condition=models.Q(pending=True) & models.Q(vehicle__isnull=False),
                fields=['vehicle', 'to_operator'],
                name='unique_pending_operator',
            ),
        ),
        migrations.AddConstraint(
            model_name='vehiclerevision',
            constraint=models.UniqueConstraint(
                condition=models.Q(pending=True) & models.Q(vehicle__isnull=False),
                fields=['vehicle', 'to_type'],
                name='unique_pending_type',
            ),
        ),
        migrations.AddConstraint(
            model_name='vehiclerevision',
            constraint=models.UniqueConstraint(
                condition=models.Q(pending=True) & models.Q(vehicle__isnull=False),
                fields=['vehicle', 'to_livery'],
                name='unique_pending_livery',
            ),
        ),
    ]
