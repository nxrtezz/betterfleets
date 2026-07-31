from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0045_remove_unique_vehicle_review_constraint"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="dvla_tax_status",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="dvla_tax_status_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
