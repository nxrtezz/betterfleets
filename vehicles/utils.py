import math

from django.core.cache import caches
from django.conf import settings
from django.core.cache.backends.base import InvalidCacheBackendError

from .models import VehicleRevision, VehicleRevisionFeature

try:
    redis_client = caches["redis"]._cache.get_client()
except InvalidCacheBackendError:
    redis_client = None


def filename_from_content_disposition(response) -> str:
    # really not fully RFC 6266 compliant
    return response.headers["Content-Disposition"].split("filename", 1)[1][2:-1]


def archive_avl_data(source, data: bytes | str, filename: str):
    if path := settings.AVL_ARCHIVE_DIR:
        path = path / str(source.id)
        if not path.exists():
            path.mkdir(parents=True)
        path /= filename
        if type(data) is str:
            path.write_text(data)
        else:
            path.write_bytes(data)


def calculate_bearing(a, b):
    a_lat = math.radians(a.y)
    a_lon = math.radians(a.x)
    b_lat = math.radians(b.y)
    b_lon = math.radians(b.x)

    y = math.sin(b_lon - a_lon) * math.cos(b_lat)
    x = math.cos(a_lat) * math.sin(b_lat) - math.sin(a_lat) * math.cos(
        b_lat
    ) * math.cos(b_lon - b_lon)

    bearing_radians = math.atan2(y, x)
    bearing_degrees = math.degrees(bearing_radians)

    if bearing_degrees < 0:
        bearing_degrees += 360

    return int(round(bearing_degrees))


def get_revision(vehicle, data):
    revision = VehicleRevision(vehicle=vehicle, changes={})
    features = []

    # create a VehicleRevision record

    if "spare_ticket_machine" in data:
        data["notes"] = (
            "Spare ticket machine" if data.pop("spare_ticket_machine") else ""
        )

    for field in (
        "withdrawn",
        "preserved",
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
    ):
        if field in data:
            from_value = "Yes" if getattr(revision.vehicle, field) else "No"
            to_value = "Yes" if data.pop(field) else "No"
            revision.changes[field] = f"-{from_value}\n+{to_value}"

    if "vehicle_type" in data:
        vehicle_type = data.pop("vehicle_type")
        revision.from_type = revision.vehicle.vehicle_type
        revision.to_type = vehicle_type

    # operator has its own ForeignKey fields:
    if "operator" in data:
        revision.from_operator = revision.vehicle.operator
        revision.to_operator = data.pop("operator")

    # operated_by has its own ForeignKey fields:
    if "operated_by" in data:
        revision.from_operated_by = revision.vehicle.operated_by
        revision.to_operated_by = data.pop("operated_by")

    if "colours" in data:
        livery = data.pop("colours")
        if revision.vehicle.livery_id != (livery and livery.id):
            revision.from_livery = revision.vehicle.livery
            revision.to_livery = livery
            if revision.vehicle.colours:
                revision.changes["colours"] = f"-{revision.vehicle.colours}\n+"

    if "garage" in data:
        garage = data.pop("garage")
        if garage or revision.vehicle.garage:
            revision.from_garage = revision.vehicle.garage
            revision.to_garage = garage

    if "other_colour" in data:
        to_colour = data.pop("other_colour")
        revision.from_livery = revision.vehicle.livery
        if revision.vehicle.colours != to_colour:
            revision.changes["colours"] = f"-{revision.vehicle.colours}\n+{to_colour}"

    if "features" in data or "accessibility_features" in data:
        current_features = list(revision.vehicle.features.all())
        current_standard_features = [
            feature for feature in current_features if feature.category == feature.Category.FEATURE
        ]
        current_accessibility_features = [
            feature
            for feature in current_features
            if feature.category == feature.Category.ACCESSIBILITY
        ]
        requested_standard_features = list(
            data.pop("features", current_standard_features)
        )
        requested_accessibility_features = list(
            data.pop("accessibility_features", current_accessibility_features)
        )
        requested_features = requested_standard_features + requested_accessibility_features
        for feature in current_features:
            if feature not in requested_features:
                features.append(
                    VehicleRevisionFeature(
                        revision=revision, feature=feature, add=False
                    )
                )
        for feature in requested_features:
            if feature not in current_features:
                features.append(
                    VehicleRevisionFeature(revision=revision, feature=feature, add=True)
                )

    if "summary" in data:
        revision.message = data.pop("summary")

    if "fleet_number" in data:
        revision.changes["fleet number"] = (
            f"-{vehicle.fleet_code or vehicle.fleet_number or ''}\n+{data.pop('fleet_number') or ''}"
        )

    if "previous_reg" in data:
        revision.changes["previous reg"] = (
            f"-{vehicle.prev_registration}\n+{data.pop('previous_reg')}"
        )

    for field in ("reg", "notes", "branding", "rear_advert", "name"):
        if field in data:
            from_value = getattr(vehicle, field)
            to_value = data.pop(field)
            revision.changes[field] = f"-{from_value}\n+{to_value}"

    if "joined_fleet" in data:
        from_value = vehicle.joined_fleet or ""
        to_value = data.pop("joined_fleet") or ""
        if from_value != to_value:
            revision.changes["joined_fleet"] = f"-{from_value}\n+{to_value}"

    if "left_fleet" in data:
        from_value = vehicle.left_fleet or ""
        to_value = data.pop("left_fleet") or ""
        if from_value != to_value:
            revision.changes["left_fleet"] = f"-{from_value}\n+{to_value}"

    if "previous_operators" in data:
        import json
        from_value = json.dumps(vehicle.previous_operators, indent=2) if vehicle.previous_operators else ""
        to_value = data.pop("previous_operators") or ""
        if from_value != to_value:
            revision.changes["previous_operators"] = f"-{from_value}\n+{to_value}"

    if "operator_vehicle_columns" in data:
        for key, to_value in data.pop("operator_vehicle_columns").items():
            from_value = (vehicle.data or {}).get(key, "")
            revision.changes[f"data:{key}"] = f"-{from_value}\n+{to_value}"

    if "advanced" in data:
        advanced_data = dict(vehicle.advanced or {})
        for key, to_value in data.pop("advanced").items():
            from_value = advanced_data.get(key, "")
            revision.changes[f"advanced:{key}"] = f"-{from_value}\n+{to_value}"

    # Handle any summary field that might be present
    if "summary" in data:
        data.pop("summary")

    assert not data

    return revision, features


def apply_revision(revision, features=None):
    changed_fields = []
    vehicle = revision.vehicle

    if revision.from_type_id != revision.to_type_id:
        vehicle.vehicle_type_id = revision.to_type_id
        changed_fields.append("vehicle_type")

    for field in ("operator", "livery", "garage"):
        from_value = getattr(revision, f"from_{field}_id")
        to_value = getattr(revision, f"to_{field}_id")
        if from_value != to_value:
            setattr(vehicle, f"{field}_id", to_value)
            changed_fields.append(field)

    for field in revision.changes:
        value = revision.changes[field]
        from_value, to_value = value.split("\n")
        assert to_value[0] == "+"
        to_value = to_value[1:]

        if field in ("reg", "notes", "branding", "rear_advert", "name", "colours"):
            setattr(vehicle, field, to_value)
            changed_fields.append(field)

        elif field == "previous reg":
            vehicle.prev_registration = to_value
            changed_fields.append("prev_registration")

        elif field == "fleet number":
            vehicle.fleet_code = to_value
            if "/" in to_value:
                to_value = to_value.split("/", 1)[1]
            if to_value.isdigit():
                vehicle.fleet_number = int(to_value)
            else:
                vehicle.fleet_number = None
            changed_fields.append("fleet_number")
            changed_fields.append("fleet_code")

        elif field in (
            "withdrawn",
            "preserved",
            "fleet_support_vehicle",
            "vor",
            "awaiting_delivery",
            "trainer_vehicle",
            "demonstrator",
        ):
            if to_value == "Yes":
                setattr(vehicle, field, True)
            else:
                assert to_value == "No"
                setattr(vehicle, field, False)
            changed_fields.append(field)

        elif field.startswith("data:"):
            data_key = field.split(":", 1)[1]
            data = dict(vehicle.data or {})
            if to_value:
                data[data_key] = to_value
            else:
                data.pop(data_key, None)
            vehicle.data = data or None
            changed_fields.append("data")

        elif field in ("joined_fleet", "left_fleet"):
            setattr(vehicle, field, to_value)
            changed_fields.append(field)

        elif field == "previous_operators":
            import json
            if to_value:
                try:
                    vehicle.previous_operators = json.loads(to_value)
                except json.JSONDecodeError:
                    # If JSON is invalid, keep the original value
                    pass
            else:
                vehicle.previous_operators = None
            changed_fields.append("previous_operators")

        elif field.startswith("advanced:"):
            field_name = field.split(":", 1)[1]
            # Store advanced fields in the JSONField
            advanced_data = dict(vehicle.advanced or {})
            # Convert string values back to appropriate types based on the form logic
            if isinstance(to_value, str):
                if to_value.lower() == "true":
                    to_value = True
                elif to_value.lower() == "false":
                    to_value = False
                elif to_value == "":
                    to_value = None
                elif to_value.isdigit():
                    to_value = int(to_value)
                # Handle date strings (ISO format YYYY-MM-DD)
                elif len(to_value) == 10 and to_value[4] == "-" and to_value[7] == "-":
                    try:
                        from datetime import datetime
                        to_value = datetime.strptime(to_value, "%Y-%m-%d").date()
                    except (ValueError, AttributeError):
                        pass  # Keep as string if not a valid date
            advanced_data[field_name] = to_value
            vehicle.advanced = advanced_data
            changed_fields.append("advanced")

        else:
            assert False

    vehicle.save(update_fields=changed_fields)

    if features is None:
        features = revision.vehiclerevisionfeature_set.all()

    for feature in features:
        if feature.add:
            vehicle.features.add(feature.feature_id)
        else:
            vehicle.features.remove(feature.feature_id)
