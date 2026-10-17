# Generated migration for BetterFleets changes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bustimes', '0009_remove_sirilink_vehicle_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='route',
            name='completed',
            field=models.BooleanField(default=False, help_text='User has ridden this route'),
        ),
    ]
