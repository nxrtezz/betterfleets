# Generated manually for API key authentication

from django.db import migrations, models
import django.utils.timezone
import secrets


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_user_driving_logging_public_alter_discordlinkcode_id_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='APIKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(editable=False, max_length=64, unique=True)),
                ('name', models.CharField(help_text='A name to identify this API key', max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to='accounts.user')),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]
