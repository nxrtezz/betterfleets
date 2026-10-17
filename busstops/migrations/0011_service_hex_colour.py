# Generated migration for BetterFleets changes

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('busstops', '0010_organisation_and_logos'),
    ]

    operations = [
        migrations.AddField(
            model_name='service',
            name='hex_colour',
            field=models.CharField(blank=True, help_text='Hex colour code for single route (e.g. #FF0000)', max_length=7),
        ),
    ]
