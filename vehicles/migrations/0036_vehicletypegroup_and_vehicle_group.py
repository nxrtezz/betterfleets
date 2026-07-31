from django.db import migrations, models
import django.db.models.deletion
from django.db.models.functions import Upper


def forwards(apps, schema_editor):
    Manufacturer = apps.get_model("busstops", "Manufacturer")
    VehicleType = apps.get_model("vehicles", "VehicleType")
    VehicleTypeGroup = apps.get_model("vehicles", "VehicleTypeGroup")

    manufacturers = {
        manufacturer.id: manufacturer
        for manufacturer in Manufacturer.objects.all().only("id")
    }
    group_cache = {}

    for vehicle_type in VehicleType.objects.select_related("manufacturer", "primary_type").order_by("name"):
        manufacturer_id = vehicle_type.manufacturer_id
        if not manufacturer_id or manufacturer_id not in manufacturers:
            continue
        group_name = vehicle_type.primary_type.name if vehicle_type.primary_type_id else vehicle_type.name
        group_key = (manufacturer_id, group_name.casefold())
        vehicle_group = group_cache.get(group_key)
        if vehicle_group is None:
            vehicle_group, _created = VehicleTypeGroup.objects.get_or_create(
                manufacturer_id=manufacturer_id,
                name=group_name,
            )
            group_cache[group_key] = vehicle_group
        vehicle_type.vehicle_group_id = vehicle_group.id
        vehicle_type.save(update_fields=["vehicle_group"])


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0030_manufacturer_and_sites"),
        ("vehicles", "0035_vehicletype_primary_type_and_active_production"),
    ]

    operations = [
        migrations.CreateModel(
            name="VehicleTypeGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                (
                    "manufacturer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vehicle_type_groups",
                        to="busstops.manufacturer",
                        verbose_name="manufactor",
                    ),
                ),
            ],
            options={
                "ordering": ("manufacturer__name", "name"),
            },
        ),
        migrations.AddConstraint(
            model_name="vehicletypegroup",
            constraint=models.UniqueConstraint(
                Upper("name"),
                "manufacturer",
                name="vehicles_vehicle_type_group_unique_name_per_manufacturer",
            ),
        ),
        migrations.AddField(
            model_name="vehicletype",
            name="vehicle_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="vehicle_types",
                to="vehicles.vehicletypegroup",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="vehicletype",
            name="primary_type",
        ),
    ]
