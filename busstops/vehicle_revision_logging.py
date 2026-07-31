from __future__ import annotations

from typing import Any

from django.utils import timezone


TRACKED_FIELDS = (
    "operator_id",
    "vehicle_type_id",
    "livery_id",
    "fleet_code",
    "fleet_number",
    "reg",
    "prev_registration",
    "withdrawn",
    "preserved",
    "fleet_support_vehicle",
    "vor",
    "awaiting_delivery",
    "trainer_vehicle",
    "demonstrator",
    "branding",
    "name",
    "notes",
    "colours",
    "data",
)


def snapshot_vehicle(vehicle) -> dict[str, Any]:
    return {field: getattr(vehicle, field, None) for field in TRACKED_FIELDS}


def bool_label(value):
    return "Yes" if value else "No"


def text_value(value):
    if value is None:
        return ""
    return str(value)


def changed_text(before, after):
    return f"-{text_value(before)}\n+{text_value(after)}"


def previous_reg(snapshot):
    if snapshot.get("prev_registration"):
        return snapshot["prev_registration"]
    data = snapshot.get("data")
    if isinstance(data, dict):
        return data.get("Previous reg") or ""
    return ""


def build_vehicle_revision(vehicle, before, *, user=None, message="Vehicle data updated"):
    from vehicles.models import VehicleRevision

    after = snapshot_vehicle(vehicle)
    revision = VehicleRevision(
        vehicle=vehicle,
        changes={},
        message=message,
        user=user,
        approved_by=user,
        created_at=timezone.now(),
        approved_at=timezone.now(),
        pending=False,
        disapproved=False,
    )

    if before.get("operator_id") != after.get("operator_id"):
        revision.from_operator_id = before.get("operator_id")
        revision.to_operator_id = after.get("operator_id")

    if before.get("vehicle_type_id") != after.get("vehicle_type_id"):
        revision.from_type_id = before.get("vehicle_type_id")
        revision.to_type_id = after.get("vehicle_type_id")

    if before.get("livery_id") != after.get("livery_id"):
        revision.from_livery_id = before.get("livery_id")
        revision.to_livery_id = after.get("livery_id")

    before_fleet = before.get("fleet_code") or before.get("fleet_number") or ""
    after_fleet = after.get("fleet_code") or after.get("fleet_number") or ""
    if text_value(before_fleet) != text_value(after_fleet):
        revision.changes["fleet number"] = changed_text(before_fleet, after_fleet)

    for field in ("reg", "notes", "branding", "name", "colours"):
        if text_value(before.get(field)) != text_value(after.get(field)):
            revision.changes[field] = changed_text(before.get(field), after.get(field))

    for field in (
        "withdrawn",
        "preserved",
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
    ):
        if bool(before.get(field)) != bool(after.get(field)):
            revision.changes[field] = changed_text(
                bool_label(before.get(field)),
                bool_label(after.get(field)),
            )

    before_previous_reg = previous_reg(before)
    after_previous_reg = previous_reg(after)
    if before_previous_reg != after_previous_reg:
        revision.changes["previous reg"] = changed_text(
            before_previous_reg,
            after_previous_reg,
        )

    if (
        revision.from_operator_id != revision.to_operator_id
        or revision.from_type_id != revision.to_type_id
        or revision.from_livery_id != revision.to_livery_id
        or revision.changes
    ):
        return revision
    return None


def log_vehicle_revision(vehicle, before, *, user=None, message="Vehicle data updated"):
    revision = build_vehicle_revision(vehicle, before, user=user, message=message)
    if revision:
        revision.save()
    return revision
