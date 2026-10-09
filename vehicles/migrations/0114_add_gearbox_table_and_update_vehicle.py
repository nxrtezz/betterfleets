from django.db import migrations, models
import django.db.models.deletion


def convert_gearbox_to_null(apps, schema_editor):
    """Convert all gearbox values to NULL before altering to ForeignKey."""
    Vehicle = apps.get_model('vehicles', 'Vehicle')
    Vehicle.objects.all().update(gearbox=None)


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0113_chassis_gearbox_engine_emissionsrating'),
    ]

    operations = [
        migrations.CreateModel(
            name='Gearbox',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'ordering': ('name',),
            },
        ),
        migrations.RunPython(convert_gearbox_to_null, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='vehicle',
            name='gearbox',
            field=models.ForeignKey(blank=True, help_text='Vehicle gearbox/transmission type', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vehicles', to='vehicles.gearbox'),
        ),
    ]
