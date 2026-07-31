# Historical fleet rows are full Vehicle rows (historical_fleet FK); drop HistoricalFleetVehicle.

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Upper


def migrate_hfv_to_vehicle(apps, schema_editor):
    HFV = apps.get_model("vehicles", "HistoricalFleetVehicle")
    Vehicle = apps.get_model("vehicles", "Vehicle")
    VehicleType = apps.get_model("vehicles", "VehicleType")
    Livery = apps.get_model("vehicles", "Livery")
    Garage = apps.get_model("bustimes", "Garage")

    for hv in HFV.objects.select_related("fleet").iterator():
        fleet = hv.fleet
        code = (
            (hv.code or hv.fleet_code or "").strip()
            or (
                str(hv.fleet_number)
                if hv.fleet_number is not None
                else ""
            )
            or (hv.reg or "").strip()
        )
        if not code:
            code = f"hist-{hv.pk}"

        v = Vehicle(
            operator_id=fleet.operator_id,
            historical_fleet_id=fleet.id,
            fleet_number=hv.fleet_number,
            fleet_code=hv.fleet_code or "",
            reg=hv.reg or "",
            code=code,
            branding=hv.branding or "",
            name=hv.name or "",
            notes=hv.notes or "",
            colours=hv.colours or "",
            data=hv.data,
            livery_id=hv.livery_id,
            linked_vehicle_id=hv.linked_vehicle_id,
        )
        if hv.vehicle_type_name and hv.vehicle_type_name.strip():
            vt = VehicleType.objects.filter(
                name__iexact=hv.vehicle_type_name.strip()
            ).first()
            if vt:
                v.vehicle_type_id = vt.id
        if hv.garage_name and hv.garage_name.strip():
            gn = hv.garage_name.strip()
            g = (
                Garage.objects.filter(operator_id=fleet.operator_id)
                .filter(Q(name__iexact=gn) | Q(code__iexact=gn))
                .first()
            )
            if g:
                v.garage_id = g.id
        if not v.livery_id and hv.data and isinstance(hv.data, dict):
            lid = hv.data.get("livery_id")
            if lid and Livery.objects.filter(pk=lid).exists():
                v.livery_id = lid
        v.save()


def backwards_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("vehicles", "0026_historicalfleetvehicle_livery"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="historical_fleet",
            field=models.ForeignKey(
                blank=True,
                help_text="When set, this row is a stored historical snapshot (not the live fleet list).",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="vehicles",
                to="vehicles.historicalfleet",
            ),
        ),
        migrations.AddField(
            model_name="vehicle",
            name="linked_vehicle",
            field=models.ForeignKey(
                blank=True,
                help_text="For historical snapshot rows: optional link to the corresponding current fleet vehicle.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="linked_historical_snapshots",
                to="vehicles.vehicle",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="vehicle",
            name="vehicle_operator_and_code",
        ),
        migrations.AddConstraint(
            model_name="vehicle",
            constraint=models.UniqueConstraint(
                Upper("code"),
                "operator",
                condition=Q(historical_fleet__isnull=True),
                name="vehicle_operator_and_code_live",
            ),
        ),
        migrations.AddConstraint(
            model_name="vehicle",
            constraint=models.UniqueConstraint(
                Upper("code"),
                "historical_fleet",
                condition=Q(historical_fleet__isnull=False),
                name="vehicle_historical_fleet_code_uniq",
            ),
        ),
        migrations.RunPython(migrate_hfv_to_vehicle, backwards_noop),
        migrations.DeleteModel(name="HistoricalFleetVehicle"),
    ]

