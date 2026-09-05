# Generated migration to add emissions advanced field

from django.db import migrations


def add_emissions_field(apps, schema_editor):
    AdvancedField = apps.get_model('vehicles', 'AdvancedField')
    AdvancedField.objects.create(
        name='Emissions rating',
        slug='emissions',
        field_type='text',
        help_text='Vehicle emissions rating (e.g., Euro 6)',
        display_order=110
    )


def remove_emissions_field(apps, schema_editor):
    AdvancedField = apps.get_model('vehicles', 'AdvancedField')
    AdvancedField.objects.filter(slug='emissions').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0100_add_length_advanced_field'),
    ]

    operations = [
        migrations.RunPython(add_emissions_field, remove_emissions_field),
    ]
