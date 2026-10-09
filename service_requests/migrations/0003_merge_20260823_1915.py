# Merge migration

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('service_requests', '0002_request_historical'),
        ('service_requests', '0002_historicalrequest_and_more'),
    ]

    operations = [
    ]
