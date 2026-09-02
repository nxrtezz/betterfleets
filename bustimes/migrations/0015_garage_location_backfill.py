import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


def copy_legacy_depots_to_garages(apps, schema_editor):
    Depot = apps.get_model("busstops", "Depot")
    Garage = apps.get_model("bustimes", "Garage")

    for depot in Depot.objects.all().iterator():
        garage = (
            Garage.objects.filter(operator_id=depot.operator_id, name=depot.name)
            .order_by("id")
            .first()
        )
        if garage is None:
            garage = Garage(
                operator_id=depot.operator_id,
                code="",
                name=depot.name,
                location=depot.location,
                is_manual=True,
            )
            garage.save()
            continue

        update_fields = []
        if depot.location and not garage.location:
            garage.location = depot.location
            update_fields.append("location")
        if not garage.is_manual:
            garage.is_manual = True
            update_fields.append("is_manual")
        if update_fields:
            garage.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("busstops", "0028_route_notice"),
        ("bustimes", "0014_garage_fleet_metadata"),
    ]

    operations = [
        migrations.RunPython(copy_legacy_depots_to_garages, migrations.RunPython.noop),
    ]
