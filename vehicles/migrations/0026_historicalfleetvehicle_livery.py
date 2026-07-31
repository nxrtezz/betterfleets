# Generated manually for HistoricalFleetVehicle.livery FK

from django.db import migrations, models
import django.db.models.deletion


def forwards_copy_livery_from_json(apps, schema_editor):
    HistoricalFleetVehicle = apps.get_model("vehicles", "HistoricalFleetVehicle")
    Livery = apps.get_model("vehicles", "Livery")
    for hv in HistoricalFleetVehicle.objects.exclude(data__isnull=True).iterator():
        data = hv.data
        if not data:
            continue
        lid = data.get("livery_id")
        if not lid or hv.livery_id:
            continue
        if Livery.objects.filter(pk=lid).exists():
            hv.livery_id = lid
            hv.save()


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0025_historical_fleet"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalfleetvehicle",
            name="livery",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="historical_fleet_vehicles",
                to="vehicles.livery",
            ),
        ),
        migrations.RunPython(forwards_copy_livery_from_json, backwards_noop),
    ]
