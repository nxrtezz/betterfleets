# Generated migration for adding flickr_url and author fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('photos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='photo',
            name='flickr_url',
            field=models.URLField(blank=True, null=True, help_text='Enter a Flickr photo URL to download the image', verbose_name='Flickr URL'),
        ),
        migrations.AddField(
            model_name='photo',
            name='author',
            field=models.CharField(blank=True, max_length=255, help_text='Photo author from Flickr'),
        ),
    ]
