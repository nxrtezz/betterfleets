# Generated migration for BetterFleets changes

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('busstops', '0009_stopusage_inbound_stopusage_line_name_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Organisation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.SlugField(max_length=48, unique=True)),
                ('name', models.CharField(max_length=100)),
                ('url', models.URLField(blank=True)),
                ('description', models.TextField(blank=True)),
                ('logo', models.ImageField(blank=True, null=True, upload_to='organisation_logos/')),
            ],
        ),
        migrations.AddField(
            model_name='operatorgroup',
            name='organisation',
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, to='busstops.organisation'),
        ),
        migrations.AddField(
            model_name='operatorgroup',
            name='logo',
            field=models.ImageField(blank=True, null=True, upload_to='operator_group_logos/'),
        ),
        migrations.AddField(
            model_name='operator',
            name='logo',
            field=models.ImageField(blank=True, null=True, upload_to='operator_logos/'),
        ),
    ]
