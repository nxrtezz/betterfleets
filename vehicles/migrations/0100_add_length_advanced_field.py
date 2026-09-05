# Generated migration to add length advanced field

from django.db import migrations


def add_length_field(apps, schema_editor):
    AdvancedField = apps.get_model('vehicles', 'AdvancedField')
    AdvancedField.objects.create(
        name='Length',
        slug='length',
        field_type='number',
        help_text='Vehicle length in meters',
        display_order=100
    )


def remove_length_field(apps, schema_editor):
    AdvancedField = apps.get_model('vehicles', 'AdvancedField')
    AdvancedField.objects.filter(slug='length').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0099_remove_busgroup_vehicles_and_add_dates'),
    ]

    operations = [
        migrations.RunPython(add_length_field, remove_length_field),
    ]
