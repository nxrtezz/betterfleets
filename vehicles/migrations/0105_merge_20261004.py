# Generated migration to resolve conflicting migrations
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('vehicles', '0099_alter_livery_css_fields'),
        ('vehicles', '0099_vehicle_technical_specs'),
        ('vehicles', '0099_vehiclerevision_permissions'),
        ('vehicles', '0104_vehicle_first_tracked_at'),
        ('vehicles', '0103_merge_20260903_0015'),
    ]

    operations = [
    ]
