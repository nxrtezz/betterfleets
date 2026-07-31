# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('vehicles', '0060_merge_20260606_2129'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='joined_fleet',
            field=models.CharField(blank=True, help_text='MM-YYYY format (e.g., 01-2024)', max_length=7),
        ),
        migrations.AddField(
            model_name='vehicle',
            name='left_fleet',
            field=models.CharField(blank=True, help_text='MM-YYYY format (e.g., 12-2024)', max_length=7),
        ),
    ]
