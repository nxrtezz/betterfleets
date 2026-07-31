from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0046_vehicle_dvla_tax_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="dvla_euro_status",
            field=models.CharField(blank=True, max_length=32),
        ),
    ]
