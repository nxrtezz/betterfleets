# Generated migration for adding author field only (flickr_url already exists)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('photos', '0002_add_flickr_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='photo',
            name='author',
            field=models.CharField(blank=True, max_length=255, help_text='Photo author from Flickr'),
        ),
    ]
