from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0030_manufacturer_and_sites"),
        ("vehicles", "0033_merge_0024_vehicle_status_flags_0032_historicallivery_external_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicletype",
            name="manufacturer",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to="busstops.manufacturer", verbose_name="manufactor"),
        ),
    ]
