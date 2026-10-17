from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import BooleanField, Case, Count, Exists, IntegerField, OuterRef, Q, Subquery, Sum, Value, When

from busstops.models import Operator
from vehicles.models import Vehicle

# TODO: These models don't exist - commented out to fix build
# from .models import FleetRideLog, FleetDrivingLog, FleetPhotoLog

User = get_user_model()
BETA_PERMISSION = "fleet.use_beta_features"


@dataclass(frozen=True)
class CompletionSummary:
    total: int
    logged: int

    @property
    def percentage(self) -> float:
        if not self.total:
            return 0.0
        return self.logged / self.total * 100


def _completion_excluded_vehicle_query() -> Q:
    return Q(vor=True) | Q(trainer_vehicle=True) | Q(fleet_support_vehicle=True) | Q(withdrawn=True) | Q(preserved=True)


def _completion_excluded_ride_log_query() -> Q:
    return (
        Q(vehicle__vor=True)
        | Q(vehicle__trainer_vehicle=True)
        | Q(vehicle__fleet_support_vehicle=True)
        | Q(vehicle__withdrawn=True)
        | Q(vehicle__preserved=True)
    )


def user_can_use_beta_features(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and user.has_perm(BETA_PERMISSION))


def get_vehicle_lookup_queryset():
    return Vehicle.objects.select_related("operator", "vehicle_type")


def annotate_logged_state(queryset, user):
    # TODO: FleetRideLog model doesn't exist - returning queryset unchanged
    return queryset


def has_vehicle_been_logged(user, vehicle) -> bool:
    # TODO: FleetRideLog model doesn't exist - returning False
    return False


def create_ride_log(user, vehicle):
    # TODO: FleetRideLog model doesn't exist - raise error
    raise ValueError("FleetRideLog model not available")


def has_vehicle_been_driven(user, vehicle) -> bool:
    # TODO: FleetDrivingLog model doesn't exist - returning False
    return False


def create_driving_log(user, vehicle, notes=""):
    # TODO: FleetDrivingLog model doesn't exist - raise error
    raise ValueError("FleetDrivingLog model not available")


def bulk_log_vehicles_for_user(user, vehicles):
    # TODO: FleetRideLog model doesn't exist - return zeros
    return 0, len(vehicles)


def bulk_drive_vehicles_for_user(user, vehicles):
    # TODO: FleetDrivingLog model doesn't exist - return zeros
    return 0, len(vehicles)


def set_ride_log_state(user, vehicle, *, logged: bool):
    # TODO: FleetRideLog model doesn't exist - return None, False
    return None, False


def set_driving_log_state(user, vehicle, *, logged: bool):
    # TODO: FleetDrivingLog model doesn't exist - return None, False
    return None, False


def sync_ride_logs_for_queryset(user, vehicles, selected_vehicle_ids):
    # TODO: FleetRideLog model doesn't exist - return zeros
    return 0, 0


def sync_driving_logs_for_queryset(user, vehicles, selected_vehicle_ids):
    # TODO: FleetDrivingLog model doesn't exist - return zeros
    return 0, 0


def get_completion_summary_for_queryset(vehicle_ids_or_queryset, user) -> CompletionSummary:
    # TODO: FleetRideLog model doesn't exist - return empty summary
    if isinstance(vehicle_ids_or_queryset, list):
        total = len(vehicle_ids_or_queryset)
    else:
        total = vehicle_ids_or_queryset.count()
    return CompletionSummary(total=total, logged=0)


def get_user_ride_stats(user) -> dict:
    # TODO: FleetRideLog model doesn't exist - return empty stats
    return {
        "vehicles": 0,
        "operators": 0,
        "types": 0,
        "overall_percentage": 0.0,
        "overall_total": 0,
    }


def get_user_driving_stats(user) -> dict:
    # TODO: FleetDrivingLog model doesn't exist - return empty stats
    return {
        "vehicles": 0,
        "operators": 0,
        "types": 0,
        "overall_percentage": 0.0,
        "overall_total": 0,
    }


def get_personal_operator_rankings(user, limit=20):
    # TODO: FleetRideLog model doesn't exist - return empty list
    return []


def get_personal_driving_operator_rankings(user, limit=20):
    # TODO: FleetDrivingLog model doesn't exist - return empty list
    return []


def get_personal_type_rankings(user, limit=20):
    # TODO: FleetRideLog model doesn't exist - return empty list
    return []


def get_personal_driving_type_rankings(user, limit=20):
    # TODO: FleetDrivingLog model doesn't exist - return empty list
    return []


def get_overall_operator_rankings(limit=20):
    # TODO: FleetRideLog model doesn't exist - return empty list
    return []


def get_overall_type_rankings(limit=20):
    # TODO: FleetRideLog model doesn't exist - return empty list
    return []


def find_matching_vehicles(query: str, noc: str = ""):
    query = (query or "").strip()
    noc = (noc or "").strip()
    if not query:
        return []

    queryset = get_vehicle_lookup_queryset()
    if noc:
        queryset = queryset.filter(operator__noc__iexact=noc)

    compact = query.replace(" ", "").upper()
    matches = list(queryset.filter(reg__iexact=compact).order_by("operator__name", "fleet_number", "fleet_code", "code")[:10])
    if matches:
        return matches

    matches = list(queryset.filter(fleet_code__iexact=query).order_by("operator__name", "fleet_number", "fleet_code", "code")[:10])
    if matches:
        return matches

    if compact.isdigit():
        matches = list(
            queryset.filter(Q(fleet_number=int(compact)) | Q(fleet_code__iexact=compact))
            .order_by("operator__name", "fleet_number", "fleet_code", "code")[:10]
        )
        if matches:
            deduped = []
            seen = set()
            for vehicle in matches:
                if vehicle.pk not in seen:
                    seen.add(vehicle.pk)
                    deduped.append(vehicle)
            return deduped

    return list(queryset.filter(code__iexact=query).order_by("operator__name", "fleet_number", "fleet_code", "code")[:10])


def format_vehicle_match(vehicle) -> str:
    fleet_ref = vehicle.fleet_code or vehicle.fleet_number or vehicle.code
    reg = vehicle.get_reg() if hasattr(vehicle, "get_reg") else vehicle.reg
    operator = vehicle.operator.noc if vehicle.operator_id else "NO-OP"
    return f"{operator} {fleet_ref} {reg}".strip()


def get_discord_user(discord_user_id: str):
    return User.objects.filter(discord_user_id=str(discord_user_id)).first()


# ──────────────────────────────────────────────────────────────────────────────
# Photography log functions
# ──────────────────────────────────────────────────────────────────────────────

def annotate_photographed_state(queryset, user):
    # TODO: FleetPhotoLog model doesn't exist - returning queryset unchanged
    return queryset


def has_vehicle_been_photographed(user, vehicle) -> bool:
    # TODO: FleetPhotoLog model doesn't exist - returning False
    return False


def create_photo_log(user, vehicle, notes=""):
    # TODO: FleetPhotoLog model doesn't exist - raise error
    raise ValueError("FleetPhotoLog model not available")


def set_photo_log_state(user, vehicle, *, logged: bool):
    # TODO: FleetPhotoLog model doesn't exist - return None, False
    return None, False


def get_user_photo_stats(user) -> dict:
    # TODO: FleetPhotoLog model doesn't exist - return empty stats
    return {
        "vehicles": 0,
        "operators": 0,
        "types": 0,
        "overall_percentage": 0.0,
        "overall_total": 0,
    }


def get_personal_photo_operator_rankings(user, limit=20):
    # TODO: FleetPhotoLog model doesn't exist - return empty list
    return []


def get_personal_photo_type_rankings(user, limit=20):
    # TODO: FleetPhotoLog model doesn't exist - return empty list
    return []
