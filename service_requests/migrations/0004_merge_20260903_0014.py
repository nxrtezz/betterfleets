# Merge migration to resolve dependency conflict

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('service_requests', '0003_fix_missing_photo_url_and_history_relation'),
        ('service_requests', '0003_merge_20260823_1915'),
    ]

    operations = [
    ]
