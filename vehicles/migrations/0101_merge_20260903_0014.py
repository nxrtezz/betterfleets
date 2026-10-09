# Merge migration to resolve dependency conflict

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0100_fix_missing_advancedfield_table'),
        ('vehicles', '0100_add_length_advanced_field'),
    ]

    operations = [
    ]
