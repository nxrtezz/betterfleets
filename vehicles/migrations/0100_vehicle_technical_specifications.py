# Placeholder migration to satisfy dependency chain
# This migration was referenced in production but never created in the repository
# The actual work was done in other migrations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0099_vehicle_technical_specs'),
    ]

    operations = [
        # No-op - changes already applied in other migrations
    ]
