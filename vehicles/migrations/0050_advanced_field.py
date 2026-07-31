# Generated manually for AdvancedField model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0049_merge_0048_merge_20260508_2007_0048_review_moderation'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdvancedField',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('slug', models.SlugField(max_length=255, unique=True)),
                ('field_type', models.CharField(choices=[('boolean', 'Boolean (true/false)'), ('number', 'Number'), ('text', 'Text'), ('date', 'Date'), ('url', 'URL')], default='text', max_length=20)),
                ('help_text', models.CharField(blank=True, max_length=500)),
                ('display_order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ('display_order', 'name'),
            },
        ),
    ]
