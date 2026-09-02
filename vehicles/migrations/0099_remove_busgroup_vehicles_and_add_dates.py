# Generated migration to remove vehicles field from BusGroup and add date fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0098_merge_0050_advanced_field_0097_vehicle_advanced"),
    ]

    operations = [
        # Add event_date field if it doesn't exist
        migrations.AddField(
            model_name='busgroup',
            name='event_date',
            field=models.DateField(blank=True, null=True),
        ),
        # Add event_end_date field if it doesn't exist
        migrations.AddField(
            model_name='busgroup',
            name='event_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        # Remove the vehicles ManyToMany field
        migrations.RemoveField(
            model_name='busgroup',
            name='vehicles',
        ),
    ]