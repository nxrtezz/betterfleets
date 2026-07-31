from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0021_fleet_metadata_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicallivery",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="historicallivery",
            name="is_manual",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="historicallivery",
            name="manual_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]