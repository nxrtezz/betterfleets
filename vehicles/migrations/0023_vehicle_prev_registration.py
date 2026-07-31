from django.db import migrations, models


def copy_previous_reg_from_data(apps, schema_editor):
    Vehicle = apps.get_model("vehicles", "Vehicle")
    for vehicle in Vehicle.objects.exclude(data__isnull=True).only(
        "id",
        "data",
        "prev_registration",
    ):
        if vehicle.prev_registration:
            continue
        if isinstance(vehicle.data, dict):
            previous_reg = vehicle.data.get("Previous reg")
            if previous_reg:
                vehicle.prev_registration = previous_reg.upper().replace(" ", "")
                vehicle.save(update_fields=["prev_registration"])


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0022_vehicle_preserved"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="prev_registration",
            field=models.CharField(blank=True, max_length=24),
        ),
        migrations.RunPython(copy_previous_reg_from_data, migrations.RunPython.noop),
    ]
