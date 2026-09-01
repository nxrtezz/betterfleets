from django.db import migrations, models


TECHNICAL_FIELD_ALIASES = {
    "engine": ("engine",),
    "gearbox": ("gearbox",),
    "length": ("length",),
    "capacity": ("capacity", "seating-capacity", "seating_capacity"),
    "emissions_rating": ("emissions_rating", "emissions-rating", "emissions"),
    "chassis": ("chassis",),
}


def migrate_legacy_advanced_values(apps, schema_editor):
    Vehicle = apps.get_model("vehicles", "Vehicle")
    for vehicle in Vehicle.objects.exclude(advanced__isnull=True).iterator():
        advanced = vehicle.advanced
        if not isinstance(advanced, dict):
            continue

        updates = {}
        for field_name, aliases in TECHNICAL_FIELD_ALIASES.items():
            if getattr(vehicle, field_name):
                continue
            for alias in aliases:
                value = advanced.get(alias)
                if value not in (None, ""):
                    updates[field_name] = str(value)
                    break
        if updates:
            Vehicle.objects.filter(pk=vehicle.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0099_remove_busgroup_vehicles_and_add_dates"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="capacity",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="chassis",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="emissions_rating",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="engine",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="gearbox",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="length",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.RunPython(migrate_legacy_advanced_values, migrations.RunPython.noop),
    ]
