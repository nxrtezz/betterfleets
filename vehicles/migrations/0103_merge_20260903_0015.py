# Merge migration to combine the two 0102 migrations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0102_add_float_field_type'),
        ('vehicles', '0102_fix_orphan_technical_columns'),
    ]

    operations = [
    ]
