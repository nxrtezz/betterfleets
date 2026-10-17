# Generated migration for BetterFleets changes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0027_m2m_through_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='completed',
            field=models.BooleanField(default=False, help_text='User has ridden this vehicle'),
        ),
    ]
