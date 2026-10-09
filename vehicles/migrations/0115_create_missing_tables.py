# Generated manually to fix missing tables from failed migration 0113

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0113_chassis_gearbox_engine_emissionsrating'),
    ]

    operations = [
        migrations.CreateModel(
            name='Gearbox',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'ordering': ('name',),
            },
        ),
        migrations.CreateModel(
            name='EmissionsRating',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('code', models.CharField(blank=True, max_length=50)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'verbose_name': 'emissions rating',
                'verbose_name_plural': 'emissions ratings',
                'ordering': ('name',),
            },
        ),
    ]
