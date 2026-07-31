# Generated manually for operated_by field

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0066_alter_livery_svg'),
        ('busstops', '0026_operator_fleet_list_notes'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='operated_by',
            field=models.ForeignKey(
                blank=True,
                help_text='Operator that operates this vehicle (if different from the owner)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='operated_vehicles',
                to='busstops.operator',
            ),
        ),
    ]
