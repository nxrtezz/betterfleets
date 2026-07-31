# Generated manually for UK National Rail stations support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('busstops', '0058_event_and_entity_user_attribution'),
    ]

    operations = [
        migrations.AddField(
            model_name='stoppoint',
            name='crs_code',
            field=models.CharField(blank=True, db_index=True, max_length=3, null=True, verbose_name='CRS code'),
        ),
    ]
