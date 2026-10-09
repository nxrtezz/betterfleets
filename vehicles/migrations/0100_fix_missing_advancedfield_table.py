# Placeholder migration to satisfy dependency chain
# This migration was referenced but never created in the repository

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0099_remove_busgroup_vehicles_and_add_dates'),
    ]

    operations = [
        # No-op - changes already applied in other migrations
    ]
