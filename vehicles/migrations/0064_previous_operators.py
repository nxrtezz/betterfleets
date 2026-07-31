# Generated manually to add previous_operators field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0063_merge_20260621_1800'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehicle',
            name='previous_operators',
            field=models.JSONField(blank=True, help_text="List of previous operators with joined_fleet dates. Format: [{'operator_id': 123, 'joined_fleet': '01-2024'}]", null=True),
        ),
    ]
