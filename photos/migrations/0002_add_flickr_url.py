# Generated migration for adding flickr_url field

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
    ]
