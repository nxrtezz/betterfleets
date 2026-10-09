# Merge migration

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('service_requests', '0006_category_specific_permissions'),
        ('service_requests', '0005_merge_20260919_2226'),
    ]

    operations = [
    ]
