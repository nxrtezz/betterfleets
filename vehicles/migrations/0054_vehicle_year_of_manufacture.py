# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0053_vehicle_dvla_mot_status_and_tax_choices"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="year_of_manufacture",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
