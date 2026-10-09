# Merge migration

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('service_requests', '0003_request_permissions'),
        ('service_requests', '0004_merge_20260903_0014'),
    ]

    operations = [
    ]
