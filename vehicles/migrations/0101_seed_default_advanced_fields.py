# Placeholder migration to satisfy dependency chain
# This migration was referenced but never created in the repository
# The actual work was done in other migrations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0101_merge_20260903_0014'),
    ]

    operations = [
        # No-op - changes already applied in other migrations
    ]
