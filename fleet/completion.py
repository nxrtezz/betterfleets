from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import BooleanField, Case, Count, Exists, IntegerField, OuterRef, Q, Subquery, Sum, Value, When

from busstops.models import Operator
from vehicles.models import Vehicle

from .models import FleetRideLog, FleetDrivingLog, FleetPhotoLog

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
    if not user.is_authenticated:
        return queryset
    return queryset.annotate(
        completion_excluded=Case(
            When(_completion_excluded_vehicle_query(), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
        has_logged=Exists(
            FleetRideLog.objects.filter(
                user=user,
                vehicle__reg=OuterRef("reg")
            ).exclude(vehicle__reg="")
        )
    )


def has_vehicle_been_logged(user, vehicle) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if vehicle.reg:
        return FleetRideLog.objects.filter(
            user=user,
            vehicle__reg=vehicle.reg
        ).exclude(vehicle__reg="").exists()
    return FleetRideLog.objects.filter(user=user, vehicle=vehicle).exists()


def create_ride_log(user, vehicle):
    if not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required.")
    try:
        ride_log, created = FleetRideLog.objects.get_or_create(user=user, vehicle=vehicle)
    except IntegrityError:
        ride_log = FleetRideLog.objects.get(user=user, vehicle=vehicle)
        created = False
    return ride_log, created


def has_vehicle_been_driven(user, vehicle) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "is_driver", False):
        return False
    if vehicle.reg:
        return FleetDrivingLog.objects.filter(
            user=user,
            vehicle__reg=vehicle.reg
        ).exclude(vehicle__reg="").exists()
    return FleetDrivingLog.objects.filter(user=user, vehicle=vehicle).exists()


def create_driving_log(user, vehicle, notes=""):
    if not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required.")
    if not getattr(user, "is_driver", False):
        raise ValueError("Driver status required.")
    try:
        driving_log, created = FleetDrivingLog.objects.get_or_create(
            user=user, vehicle=vehicle, defaults={"notes": notes}
        )
        if not created and notes:
            driving_log.notes = notes
            driving_log.save(update_fields=["notes"])
    except IntegrityError:
        driving_log = FleetDrivingLog.objects.get(user=user, vehicle=vehicle)
        created = False
    return driving_log, created


def bulk_log_vehicles_for_user(user, vehicles):
    created = 0
    skipped = 0
    for vehicle in vehicles:
        _, was_created = create_ride_log(user, vehicle)
        if was_created:
            created += 1
        else:
            skipped += 1
    return created, skipped


def bulk_drive_vehicles_for_user(user, vehicles):
    created = 0
    skipped = 0
    for vehicle in vehicles:
        _, was_created = create_driving_log(user, vehicle)
        if was_created:
            created += 1
        else:
            skipped += 1
    return created, skipped


def set_ride_log_state(user, vehicle, *, logged: bool):
    if logged:
        ride_log, created = create_ride_log(user, vehicle)
        return ride_log, created
    deleted, _ = FleetRideLog.objects.filter(user=user, vehicle=vehicle).delete()
    return None, bool(deleted)


def set_driving_log_state(user, vehicle, *, logged: bool):
    if logged:
        driving_log, created = create_driving_log(user, vehicle)
        return driving_log, created
    deleted, _ = FleetDrivingLog.objects.filter(user=user, vehicle=vehicle).delete()
    return None, bool(deleted)


def sync_ride_logs_for_queryset(user, vehicles, selected_vehicle_ids):
    selected_ids = {int(vehicle_id) for vehicle_id in selected_vehicle_ids}
    created = 0
    deleted = 0
    for vehicle in vehicles:
        _, changed = set_ride_log_state(
            user,
            vehicle,
            logged=vehicle.pk in selected_ids,
        )
        if vehicle.pk in selected_ids:
            created += int(changed)
        else:
            deleted += int(changed)
    return created, deleted


def sync_driving_logs_for_queryset(user, vehicles, selected_vehicle_ids):
    selected_ids = {int(vehicle_id) for vehicle_id in selected_vehicle_ids}
    created = 0
    deleted = 0
    for vehicle in vehicles:
        _, changed = set_driving_log_state(
            user,
            vehicle,
            logged=vehicle.pk in selected_ids,
        )
        if vehicle.pk in selected_ids:
            created += int(changed)
        else:
            deleted += int(changed)
    return created, deleted


def get_completion_summary_for_queryset(vehicle_ids_or_queryset, user) -> CompletionSummary:
    # Handle both vehicle IDs list and queryset
    # Convert to vehicle IDs list to avoid filter() issues with union querysets
    if isinstance(vehicle_ids_or_queryset, list):
        # If it's already a list of vehicle IDs
        vehicle_ids = vehicle_ids_or_queryset
    else:
        # If it's a queryset, extract vehicle IDs
        vehicle_ids = list(vehicle_ids_or_queryset.values_list('pk', flat=True))
    
    # Create a fresh queryset from the vehicle IDs
    queryset = Vehicle.objects.filter(pk__in=vehicle_ids)
    
    excluded_queryset = queryset.filter(_completion_excluded_vehicle_query())
    base_queryset = queryset.exclude(_completion_excluded_vehicle_query())
    total = base_queryset.values("pk").distinct().count()
    if not user.is_authenticated:
        return CompletionSummary(total=total, logged=0)
    logged_queryset = FleetRideLog.objects.filter(
        user=user,
        vehicle_id__in=vehicle_ids,
    ).values("vehicle_id").distinct()
    logged = logged_queryset.count()
    excluded_logged_total = logged_queryset.filter(
        vehicle_id__in=excluded_queryset.values("pk")
    ).count()
    total += excluded_logged_total
    return CompletionSummary(total=total, logged=logged)


def get_user_ride_stats(user) -> dict:
    all_logs = FleetRideLog.objects.filter(user=user)
    total_logged = all_logs.count()
    total_operators = (
        all_logs.filter(vehicle__operator__isnull=False)
        .values("vehicle__operator_id")
        .distinct()
        .count()
    )
    total_types = (
        all_logs.filter(vehicle__vehicle_type__isnull=False)
        .values("vehicle__vehicle_type_id")
        .distinct()
        .count()
    )
    total_vehicles = Vehicle.objects.exclude(_completion_excluded_vehicle_query()).count()
    total_vehicles += (
        all_logs.filter(_completion_excluded_ride_log_query())
        .values("vehicle_id")
        .distinct()
        .count()
    )
    summary = CompletionSummary(total=total_vehicles, logged=total_logged)
    return {
        "vehicles": total_logged,
        "operators": total_operators,
        "types": total_types,
        "overall_percentage": summary.percentage,
        "overall_total": total_vehicles,
    }


def get_user_driving_stats(user) -> dict:
    all_logs = FleetDrivingLog.objects.filter(user=user)
    total_driven = all_logs.count()
    total_operators = (
        all_logs.filter(vehicle__operator__isnull=False)
        .values("vehicle__operator_id")
        .distinct()
        .count()
    )
    total_types = (
        all_logs.filter(vehicle__vehicle_type__isnull=False)
        .values("vehicle__vehicle_type_id")
        .distinct()
        .count()
    )
    total_vehicles = Vehicle.objects.exclude(_completion_excluded_vehicle_query()).count()
    total_vehicles += (
        all_logs.filter(_completion_excluded_ride_log_query())
        .values("vehicle_id")
        .distinct()
        .count()
    )
    summary = CompletionSummary(total=total_vehicles, logged=total_driven)
    return {
        "vehicles": total_driven,
        "operators": total_operators,
        "types": total_types,
        "overall_percentage": summary.percentage,
        "overall_total": total_vehicles,
    }


def get_personal_operator_rankings(user, limit=20):
    operators = Operator.objects.annotate(
        logged_vehicle_count=Count(
            "vehicle__ride_logs__vehicle",
            distinct=True,
            filter=Q(vehicle__ride_logs__user=user)
        ),
        total_vehicle_count=Count(
            "vehicle",
            distinct=True,
            filter=~Q(vehicle__vor=True) & ~Q(vehicle__trainer_vehicle=True) & ~Q(vehicle__fleet_support_vehicle=True) & ~Q(vehicle__withdrawn=True) & ~Q(vehicle__preserved=True)
        ),
        excluded_logged_count=Count(
            "vehicle__ride_logs__vehicle",
            distinct=True,
            filter=Q(vehicle__ride_logs__user=user) & (Q(vehicle__ride_logs__vehicle__vor=True) | Q(vehicle__ride_logs__vehicle__trainer_vehicle=True) | Q(vehicle__ride_logs__vehicle__fleet_support_vehicle=True) | Q(vehicle__ride_logs__vehicle__withdrawn=True) | Q(vehicle__ride_logs__vehicle__preserved=True))
        )
    ).filter(logged_vehicle_count__gt=0).order_by("-logged_vehicle_count", "name")[:limit]
    
    for operator in operators:
        # Total = non-excluded vehicles + excluded vehicles that were logged
        total = operator.total_vehicle_count + operator.excluded_logged_count
        if total > 0:
            operator.percentage = (operator.logged_vehicle_count / total) * 100
        else:
            operator.percentage = 0
        operator.total_vehicle_count = total
    return operators


def get_personal_driving_operator_rankings(user, limit=20):
    operators = Operator.objects.annotate(
        logged_vehicle_count=Count(
            "vehicle__driving_logs__vehicle",
            distinct=True,
            filter=Q(vehicle__driving_logs__user=user)
        ),
        total_vehicle_count=Count(
            "vehicle",
            distinct=True,
            filter=~Q(vehicle__vor=True) & ~Q(vehicle__trainer_vehicle=True) & ~Q(vehicle__fleet_support_vehicle=True) & ~Q(vehicle__withdrawn=True) & ~Q(vehicle__preserved=True)
        ),
        excluded_logged_count=Count(
            "vehicle__driving_logs__vehicle",
            distinct=True,
            filter=Q(vehicle__driving_logs__user=user) & (Q(vehicle__driving_logs__vehicle__vor=True) | Q(vehicle__driving_logs__vehicle__trainer_vehicle=True) | Q(vehicle__driving_logs__vehicle__fleet_support_vehicle=True) | Q(vehicle__driving_logs__vehicle__withdrawn=True) | Q(vehicle__driving_logs__vehicle__preserved=True))
        )
    ).filter(logged_vehicle_count__gt=0).order_by("-logged_vehicle_count", "name")[:limit]
    
    for operator in operators:
        # Total = non-excluded vehicles + excluded vehicles that were logged
        total = operator.total_vehicle_count + operator.excluded_logged_count
        if total > 0:
            operator.percentage = (operator.logged_vehicle_count / total) * 100
        else:
            operator.percentage = 0
        operator.total_vehicle_count = total
    return operators


def get_personal_type_rankings(user, limit=20):
    return (
        FleetRideLog.objects.filter(
            user=user,
            vehicle__vehicle_type__isnull=False,
        )
        .values("vehicle__vehicle_type__name")
        .annotate(logged_vehicle_count=Count("vehicle_id", distinct=True))
        .order_by("-logged_vehicle_count", "vehicle__vehicle_type__name")[:limit]
    )


def get_personal_driving_type_rankings(user, limit=20):
    return (
        FleetDrivingLog.objects.filter(
            user=user,
            vehicle__vehicle_type__isnull=False,
        )
        .values("vehicle__vehicle_type__name")
        .annotate(logged_vehicle_count=Count("vehicle_id", distinct=True))
        .order_by("-logged_vehicle_count", "vehicle__vehicle_type__name")[:limit]
    )


def get_overall_operator_rankings(limit=20):
    return (
        Operator.objects.filter(vehicle__ride_logs__isnull=False)
        .annotate(logged_vehicle_count=Count("vehicle__ride_logs__vehicle", distinct=True))
        .order_by("-logged_vehicle_count", "name")[:limit]
    )


def get_overall_type_rankings(limit=20):
    return (
        FleetRideLog.objects.filter(
            vehicle__vehicle_type__isnull=False,
        )
        .values("vehicle__vehicle_type__name")
        .annotate(logged_vehicle_count=Count("vehicle_id", distinct=True))
        .order_by("-logged_vehicle_count", "vehicle__vehicle_type__name")[:limit]
    )


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
    if not user.is_authenticated:
        return queryset
    return queryset.annotate(
        has_photographed=Exists(
            FleetPhotoLog.objects.filter(
                user=user,
                vehicle__reg=OuterRef("reg")
            ).exclude(vehicle__reg="")
        ),
        photo_quantity=Case(
            When(
                Exists(
                    FleetPhotoLog.objects.filter(
                        user=user,
                        vehicle__reg=OuterRef("reg")
                    ).exclude(vehicle__reg="")
                ),
                then=Subquery(
                    FleetPhotoLog.objects.filter(
                        user=user,
                        vehicle__reg=OuterRef("reg")
                    ).exclude(vehicle__reg="").values('quantity')[:1]
                )
            ),
            default=0,
            output_field=IntegerField()
        )
    )


def has_vehicle_been_photographed(user, vehicle) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if vehicle.reg:
        return FleetPhotoLog.objects.filter(
            user=user,
            vehicle__reg=vehicle.reg
        ).exclude(vehicle__reg="").exists()
    return FleetPhotoLog.objects.filter(user=user, vehicle=vehicle).exists()


def create_photo_log(user, vehicle, notes=""):
    if not getattr(user, "is_authenticated", False):
        raise ValueError("Authenticated user required.")
    try:
        photo_log, created = FleetPhotoLog.objects.get_or_create(
            user=user, vehicle=vehicle, defaults={"notes": notes}
        )
        if not created and notes:
            photo_log.notes = notes
            photo_log.save(update_fields=["notes"])
    except IntegrityError:
        photo_log = FleetPhotoLog.objects.get(user=user, vehicle=vehicle)
        created = False
    return photo_log, created


def set_photo_log_state(user, vehicle, *, logged: bool):
    if logged:
        photo_log, created = create_photo_log(user, vehicle)
        return photo_log, created
    deleted, _ = FleetPhotoLog.objects.filter(user=user, vehicle=vehicle).delete()
    return None, bool(deleted)


def get_user_photo_stats(user) -> dict:
    all_logs = FleetPhotoLog.objects.filter(user=user)
    total_photographed = all_logs.aggregate(total=Sum('quantity'))['total'] or 0
    total_operators = (
        all_logs.filter(vehicle__operator__isnull=False)
        .values("vehicle__operator_id")
        .distinct()
        .count()
    )
    total_types = (
        all_logs.filter(vehicle__vehicle_type__isnull=False)
        .values("vehicle__vehicle_type_id")
        .distinct()
        .count()
    )
    total_vehicles = Vehicle.objects.exclude(_completion_excluded_vehicle_query()).count()
    total_vehicles += (
        all_logs.filter(_completion_excluded_ride_log_query())
        .values("vehicle_id")
        .distinct()
        .count()
    )
    summary = CompletionSummary(total=total_vehicles, logged=total_photographed)
    return {
        "vehicles": total_photographed,
        "operators": total_operators,
        "types": total_types,
        "overall_percentage": summary.percentage,
        "overall_total": total_vehicles,
    }


def get_personal_photo_operator_rankings(user, limit=20):
    operators = Operator.objects.annotate(
        logged_vehicle_count=Count(
            "vehicle__photo_logs__vehicle",
            distinct=True,
            filter=Q(vehicle__photo_logs__user=user)
        ),
        total_vehicle_count=Count(
            "vehicle",
            distinct=True,
            filter=~Q(vehicle__vor=True) & ~Q(vehicle__trainer_vehicle=True) & ~Q(vehicle__fleet_support_vehicle=True) & ~Q(vehicle__withdrawn=True) & ~Q(vehicle__preserved=True)
        ),
        excluded_logged_count=Count(
            "vehicle__photo_logs__vehicle",
            distinct=True,
            filter=Q(vehicle__photo_logs__user=user) & (Q(vehicle__photo_logs__vehicle__vor=True) | Q(vehicle__photo_logs__vehicle__trainer_vehicle=True) | Q(vehicle__photo_logs__vehicle__fleet_support_vehicle=True) | Q(vehicle__photo_logs__vehicle__withdrawn=True) | Q(vehicle__photo_logs__vehicle__preserved=True))
        )
    ).filter(logged_vehicle_count__gt=0).order_by("-logged_vehicle_count", "name")[:limit]

    for operator in operators:
        total = operator.total_vehicle_count + operator.excluded_logged_count
        if total > 0:
            operator.percentage = (operator.logged_vehicle_count / total) * 100
        else:
            operator.percentage = 0
        operator.total_vehicle_count = total
    return operators


def get_personal_photo_type_rankings(user, limit=20):
    return (
        FleetPhotoLog.objects.filter(
            user=user,
            vehicle__vehicle_type__isnull=False,
        )
        .values("vehicle__vehicle_type__name")
        .annotate(logged_vehicle_count=Count("vehicle_id", distinct=True))
        .order_by("-logged_vehicle_count", "vehicle__vehicle_type__name")[:limit]
    )


def get_recent_ride_logs(user, limit=10):
    return (
        FleetRideLog.objects
        .filter(user=user)
        .select_related("vehicle", "vehicle__operator", "vehicle__vehicle_type")
        .order_by("-created_at")[:limit]
    )


def get_recent_photo_logs(user, limit=10):
    return (
        FleetPhotoLog.objects
        .filter(user=user)
        .select_related("vehicle", "vehicle__operator", "vehicle__vehicle_type")
        .order_by("-created_at")[:limit]
    )


def get_recent_driving_logs(user, limit=10):
    return (
        FleetDrivingLog.objects
        .filter(user=user)
        .select_related("vehicle", "vehicle__operator", "vehicle__vehicle_type")
        .order_by("-created_at")[:limit]
    )


def compute_achievements(ride_stats, photo_stats, driving_stats, ride_operator_count, photo_operator_count):
    """Compute which achievement badges the user has unlocked."""
    achievements = []

    ride_count = ride_stats.get("vehicles", 0) if ride_stats else 0
    photo_count = photo_stats.get("vehicles", 0) if photo_stats else 0
    ride_pct = ride_stats.get("overall_percentage", 0) if ride_stats else 0
    drive_count = driving_stats.get("vehicles", 0) if driving_stats else 0

    achievements.append({
        "id": "first_ride",
        "name": "First Boarding",
        "description": "Log your first vehicle",
        "icon": "🚌",
        "unlocked": ride_count >= 1,
        "tier": "bronze",
    })
    achievements.append({
        "id": "first_photo",
        "name": "First Shot",
        "description": "Photograph your first vehicle",
        "icon": "📷",
        "unlocked": photo_count >= 1,
        "tier": "bronze",
    })
    achievements.append({
        "id": "fleet_explorer",
        "name": "Fleet Explorer",
        "description": "Ride vehicles from 5+ operators",
        "icon": "🗺️",
        "unlocked": ride_operator_count >= 5,
        "tier": "bronze",
    })
    achievements.append({
        "id": "century_club",
        "name": "Century Club",
        "description": "Ride 100 different vehicles",
        "icon": "💯",
        "unlocked": ride_count >= 100,
        "tier": "silver",
    })
    achievements.append({
        "id": "double_century",
        "name": "Double Century",
        "description": "Ride 200 different vehicles",
        "icon": "🎯",
        "unlocked": ride_count >= 200,
        "tier": "silver",
    })
    achievements.append({
        "id": "fleet_hunter",
        "name": "Fleet Hunter",
        "description": "Reach 50% overall fleet completion",
        "icon": "🏹",
        "unlocked": ride_pct >= 50,
        "tier": "gold",
    })
    achievements.append({
        "id": "shutterbug",
        "name": "Shutterbug",
        "description": "Photograph 50 different vehicles",
        "icon": "📸",
        "unlocked": photo_count >= 50,
        "tier": "silver",
    })
    achievements.append({
        "id": "photo_century",
        "name": "Photo Century",
        "description": "Photograph 100 different vehicles",
        "icon": "🎞️",
        "unlocked": photo_count >= 100,
        "tier": "gold",
    })
    if driving_stats:
        achievements.append({
            "id": "behind_the_wheel",
            "name": "Behind the Wheel",
            "description": "Drive your first vehicle",
            "icon": "🚗",
            "unlocked": drive_count >= 1,
            "tier": "bronze",
        })
        achievements.append({
            "id": "driver_century",
            "name": "Driver's Century",
            "description": "Drive 100 different vehicles",
            "icon": "🏎️",
            "unlocked": drive_count >= 100,
            "tier": "gold",
        })

    return achievements

