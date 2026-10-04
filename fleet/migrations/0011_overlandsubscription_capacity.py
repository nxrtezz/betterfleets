# Generated migration for capacity fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0010_overlandsubscription_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='overlandsubscription',
            name='capacity_current',
            field=models.PositiveIntegerField(default=0, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='overlandsubscription',
            name='capacity_max',
            field=models.PositiveIntegerField(default=0, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='overlandsubscription',
            name='capacity_enabled',
            field=models.BooleanField(default=False),
        ),
    ]
