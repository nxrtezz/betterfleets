# Placeholder migration to satisfy dependency chain
# This migration was referenced in production but never created in the repository
# The actual work was done in other migrations

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('service_requests', '0002_request_historical'),
    ]

    operations = [
        # No-op - changes already applied in other migrations
    ]
