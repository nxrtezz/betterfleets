from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db import connection
from django.utils import timezone
from django.utils.text import slugify

from bustimes.models import Garage
from busstops.models import Operator
from fleet.matching import match_garage_for_row, match_operator_for_row
from fleet.models import FleetPDFUpload, FleetVehicle
from vehicles.models import Livery, Vehicle, VehicleType


@dataclass(slots=True)
class ImportSummary:
    created: int = 0
    updated: int = 0
    errors: int = 0


def build_import_rows(upload: FleetPDFUpload) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for fleet_vehicle in upload.vehicles.order_by(
        "source_page", "fleet_number", "fleet_code", "code"
    ):
        operator_preview = match_operator_for_row(fleet_vehicle)
        matched_operator = (
            Operator.objects.filter(pk=operator_preview.object_id).first()
            if operator_preview.is_match and operator_preview.object_id
            else None
        )
        garage_preview = match_garage_for_row(fleet_vehicle)
        matched_garage = (
            Garage.objects.filter(pk=garage_preview.object_id).first()
            if garage_preview.is_match and garage_preview.object_id
            else None
        )

        existing_vehicle = _find_existing_vehicle(fleet_vehicle, matched_operator)
        action = "update" if existing_vehicle else "create"
        errors: list[str] = []

        if not fleet_vehicle.code and not fleet_vehicle.fleet_code and not fleet_vehicle.registration:
            errors.append("No vehicle identifier available for live import.")

        unresolved_livery = None
        if fleet_vehicle.livery:
            resolved_livery = Livery.objects.filter(name__iexact=fleet_vehicle.livery).first()
            if not resolved_livery:
                unresolved_livery = fleet_vehicle.livery
        else:
            resolved_livery = None

        rows.append(
            {
                "fleet_vehicle": fleet_vehicle,
                "row_number": fleet_vehicle.pk,
                "action": action,
                "live_vehicle": existing_vehicle,
                "operator_preview": operator_preview,
                "garage_preview": garage_preview,
                "matched_operator": matched_operator,
                "matched_garage": matched_garage,
                "resolved_livery": resolved_livery,
                "unresolved_livery": unresolved_livery,
                "errors": errors,
            }
        )

    return rows


def commit_import_rows(rows: list[dict[str, object]]) -> ImportSummary:
    summary = ImportSummary()

    for row in rows:
        if row["errors"]:
            summary.errors += 1
            continue

        try:
            with transaction.atomic():
                fleet_vehicle = row["fleet_vehicle"]
                operator = row["matched_operator"] or _create_operator(fleet_vehicle.operator_code)
                garage = row["matched_garage"]
                if not garage and fleet_vehicle.garage:
                    garage = _create_garage(fleet_vehicle.garage, operator)

                vehicle = row["live_vehicle"] or Vehicle(operator=operator)
                vehicle.operator = operator
                vehicle.code = fleet_vehicle.code or fleet_vehicle.fleet_code or fleet_vehicle.registration
                vehicle.fleet_code = fleet_vehicle.fleet_code or fleet_vehicle.fleet_number or ""
                vehicle.fleet_number = _coerce_fleet_number(fleet_vehicle.fleet_number)
                vehicle.reg = fleet_vehicle.registration
                vehicle.prev_registration = fleet_vehicle.prev_registration
                vehicle.vehicle_type = _resolve_vehicle_type(fleet_vehicle.vehicle_type)
                vehicle.livery = row["resolved_livery"]
                vehicle.colours = fleet_vehicle.colours
                vehicle.garage = garage
                vehicle.name = fleet_vehicle.name
                vehicle.branding = fleet_vehicle.branding
                vehicle.notes = _build_notes(fleet_vehicle, row["unresolved_livery"])
                vehicle.withdrawn = fleet_vehicle.withdrawn
                vehicle.preserved = fleet_vehicle.preserved
                vehicle.fleet_support_vehicle = fleet_vehicle.fleet_support_vehicle
                vehicle.vor = fleet_vehicle.vor
                vehicle.awaiting_delivery = fleet_vehicle.awaiting_delivery
                vehicle.trainer_vehicle = fleet_vehicle.trainer_vehicle
                vehicle.demonstrator = fleet_vehicle.demonstrator
                vehicle.external_id = fleet_vehicle.external_id or None
                vehicle.is_manual = True
                vehicle.manual_updated_at = timezone.now()
                vehicle.save()

                if row["action"] == "create":
                    summary.created += 1
                else:
                    summary.updated += 1
        except Exception as exc:
            row["errors"].append(str(exc))
            summary.errors += 1

    return summary


def _find_existing_vehicle(fleet_vehicle: FleetVehicle, operator: Operator | None) -> Vehicle | None:
    if not operator:
        return None

    vehicles = operator.vehicle_set.filter(**_current_vehicle_filters(preserved=False))
    if fleet_vehicle.external_id:
        vehicle = vehicles.filter(external_id=fleet_vehicle.external_id).first()
        if vehicle:
            return vehicle
    if fleet_vehicle.code:
        vehicle = vehicles.filter(code__iexact=fleet_vehicle.code).first()
        if vehicle:
            return vehicle
    if fleet_vehicle.registration:
        return vehicles.filter(reg__iexact=fleet_vehicle.registration).first()
    return None


def _create_operator(operator_code: str) -> Operator:
    code = (operator_code or "").strip().upper()
    operator = Operator.objects.filter(noc__iexact=code).first()
    if operator:
        return operator

    slug_base = slugify(code) or "operator"
    slug = slug_base
    suffix = 2
    while Operator.objects.filter(slug=slug).exists():
        slug = f"{slug_base}-{suffix}"
        suffix += 1

    return Operator.objects.create(
        noc=code,
        name=code,
        slug=slug,
        is_manual=True,
        manual_updated_at=timezone.now(),
    )


def _create_garage(garage_name: str, operator: Operator) -> Garage:
    stripped = garage_name[4:].strip() if garage_name.upper().startswith("GSC ") else garage_name.strip()
    garage = (
        Garage.objects.filter(operator=operator)
        .filter(name__iexact=stripped)
        .first()
    )
    if garage:
        return garage

    return Garage.objects.create(
        operator=operator,
        name=stripped,
        code=stripped,
        is_manual=True,
        manual_updated_at=timezone.now(),
    )


def _resolve_vehicle_type(vehicle_type_name: str) -> VehicleType | None:
    if not vehicle_type_name:
        return None
    vehicle_type = VehicleType.objects.filter(name__iexact=vehicle_type_name).first()
    if vehicle_type:
        return vehicle_type
    return VehicleType.objects.create(
        name=vehicle_type_name,
        is_manual=True,
        manual_updated_at=timezone.now(),
    )


def _coerce_fleet_number(value: str) -> int | None:
    if not value:
        return None
    if str(value).isdigit():
        return int(value)
    return None


def _build_notes(fleet_vehicle: FleetVehicle, unresolved_livery: str | None) -> str:
    parts = [fleet_vehicle.notes] if fleet_vehicle.notes else []
    if unresolved_livery:
        parts.append(f"Imported livery text: {unresolved_livery}")
    return "\n".join(part for part in parts if part)


def _current_vehicle_filters(**filters):
    try:
        with connection.cursor() as cursor:
            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, Vehicle._meta.db_table
                )
            }
    except Exception:
        columns = {
            field.column for field in Vehicle._meta.fields if getattr(field, "column", None)
        }

    unsupported = {
        "withdrawn": "withdrawn",
        "preserved": "preserved",
        "operator": "operator_id",
        "operator_id": "operator_id",
    }
    for key, column in unsupported.items():
        if key in filters and column not in columns:
            filters.pop(key)
    if "historical_fleet_id" in columns:
        filters["historical_fleet__isnull"] = True
    return filters
