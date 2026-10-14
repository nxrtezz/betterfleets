# Generated migration to add missing advanced fields for chassis, engine, gearbox, and seating capacity

from django.db import migrations


def add_missing_advanced_fields(apps, schema_editor):
    AdvancedField = apps.get_model('vehicles', 'AdvancedField')

    # Create chassis field
    AdvancedField.objects.get_or_create(
        slug='chassis',
        defaults={
            'name': 'Chassis',
            'field_type': 'text',
            'help_text': 'Vehicle chassis manufacturer/model',
            'display_order': 10
        }
    )

    # Create engine field
    AdvancedField.objects.get_or_create(
        slug='engine',
        defaults={
            'name': 'Engine',
            'field_type': 'text',
            'help_text': 'Vehicle engine manufacturer/model',
            'display_order': 20
        }
    )

    # Create gearbox field
    AdvancedField.objects.get_or_create(
        slug='gearbox',
        defaults={
            'name': 'Gearbox',
            'field_type': 'text',
            'help_text': 'Vehicle gearbox/transmission type',
            'display_order': 30
        }
    )

    # Create seating capacity field
    AdvancedField.objects.get_or_create(
        slug='seating-capacity',
        defaults={
            'name': 'Seating capacity',
            'field_type': 'number',
            'help_text': 'Vehicle seating capacity (number of passengers)',
            'display_order': 40
        }
    )


def remove_missing_advanced_fields(apps, schema_editor):
    AdvancedField = apps.get_model('vehicles', 'AdvancedField')
    AdvancedField.objects.filter(slug__in=['chassis', 'engine', 'gearbox', 'seating-capacity']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0116_fix_gearbox_column'),
    ]

    operations = [
        migrations.RunPython(add_missing_advanced_fields, remove_missing_advanced_fields),
    ]
