# Generated migration for Livery joined_fleet and left_fleet fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='livery',
            name='joined_fleet',
            field=models.CharField(blank=True, max_length=7, help_text='MM-YYYY format (e.g., 01-2024)'),
        ),
        migrations.AddField(
            model_name='livery',
            name='left_fleet',
            field=models.CharField(blank=True, max_length=7, help_text='MM-YYYY format (e.g., 12-2024)'),
        ),
    ]
