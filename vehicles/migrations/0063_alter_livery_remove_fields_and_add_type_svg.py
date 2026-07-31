# Generated migration for livery field changes

from django.db import migrations, models
import django.core.validators
import vehicles.fields
import vehicles.models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0062_remove_historicallivery_history_user_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='livery',
            name='creator',
        ),
        migrations.RemoveField(
            model_name='livery',
            name='description',
        ),
        migrations.RemoveField(
            model_name='livery',
            name='model_differences',
        ),
        migrations.RemoveField(
            model_name='livery',
            name='image',
        ),
        migrations.AddField(
            model_name='livery',
            name='livery_type',
            field=models.CharField(
                choices=[('css', 'CSS'), ('svg', 'SVG')],
                default='css',
                help_text='Type of livery: CSS gradients or SVG image',
                max_length=3
            ),
        ),
        migrations.AddField(
            model_name='livery',
            name='svg',
            field=models.FileField(
                blank=True,
                help_text='SVG file with aspect ratio 3:2 (e.g., 90x60, 180x120)',
                null=True,
                upload_to='liveries/svg',
                validators=[
                    django.core.validators.FileExtensionValidator(
                        allowed_extensions=['svg']
                    )
                ]
            ),
        ),
    ]
