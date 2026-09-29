from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST, require_safe
from django.views.decorators.csrf import csrf_exempt

from busstops.models import Operator
from vehicles.models import Vehicle, VehicleJourney, DataSource
from fleet.completion import (
    get_overall_operator_rankings,
    get_overall_type_rankings,
    get_personal_operator_rankings,
    get_personal_type_rankings,
    get_personal_driving_operator_rankings,
    get_personal_driving_type_rankings,
    get_user_ride_stats,
    get_user_driving_stats,
    get_user_photo_stats,
    get_personal_photo_operator_rankings,
    get_personal_photo_type_rankings,
    get_recent_ride_logs,
    get_recent_photo_logs,
    get_recent_driving_logs,
    compute_achievements,
)
from fleet.transittracker_scraper import run_import
from fleet.models import OverlandSubscription, PinnedOperator

User = get_user_model()


def fleet_completion(request):
    if not request.user.is_authenticated:
        raise PermissionDenied

    ride_stats = get_user_ride_stats(request.user)
    photo_stats = get_user_photo_stats(request.user)
    ride_operators = get_personal_operator_rankings(request.user)
    photo_operators = get_personal_photo_operator_rankings(request.user)

    driving_stats = None
    if request.user.is_driver:
        driving_stats = get_user_driving_stats(request.user)

    achievements = compute_achievements(
        ride_stats=ride_stats,
        photo_stats=photo_stats,
        driving_stats=driving_stats,
        ride_operator_count=len(ride_operators),
        photo_operator_count=len(photo_operators),
    )

    context = {
        "ride_stats": ride_stats,
        "photo_stats": photo_stats,
        "personal_operator_rankings": ride_operators,
        "personal_type_rankings": get_personal_type_rankings(request.user),
        "personal_photo_operator_rankings": photo_operators,
        "personal_photo_type_rankings": get_personal_photo_type_rankings(request.user),
        "overall_operator_rankings": get_overall_operator_rankings(),
        "overall_type_rankings": get_overall_type_rankings(),
        "recent_ride_logs": get_recent_ride_logs(request.user),
        "recent_photo_logs": get_recent_photo_logs(request.user),
        "achievements": achievements,
    }

    if request.user.is_driver:
        context["driving_stats"] = driving_stats
        context["personal_driving_operator_rankings"] = get_personal_driving_operator_rankings(request.user)
        context["personal_driving_type_rankings"] = get_personal_driving_type_rankings(request.user)
        context["recent_driving_logs"] = get_recent_driving_logs(request.user)

    return render(
        request,
        "fleet_completion.html",
        context,
    )


def public_fleet_completion(request, username):
    user = get_object_or_404(User, username=username)

    if not user.fleet_logging_public:
        raise PermissionDenied("This user's fleet completion is not public.")

    ride_stats = get_user_ride_stats(user)
    photo_stats = get_user_photo_stats(user)
    ride_operators = get_personal_operator_rankings(user)
    photo_operators = get_personal_photo_operator_rankings(user)

    driving_stats = None
    if user.is_driver and user.driving_logging_public:
        driving_stats = get_user_driving_stats(user)

    achievements = compute_achievements(
        ride_stats=ride_stats,
        photo_stats=photo_stats,
        driving_stats=driving_stats,
        ride_operator_count=len(ride_operators),
        photo_operator_count=len(photo_operators),
    )

    context = {
        "profile_user": user,
        "ride_stats": ride_stats,
        "photo_stats": photo_stats,
        "personal_operator_rankings": ride_operators,
        "personal_type_rankings": get_personal_type_rankings(user),
        "personal_photo_operator_rankings": photo_operators,
        "personal_photo_type_rankings": get_personal_photo_type_rankings(user),
        "overall_operator_rankings": get_overall_operator_rankings(),
        "overall_type_rankings": get_overall_type_rankings(),
        "recent_ride_logs": get_recent_ride_logs(user),
        "recent_photo_logs": get_recent_photo_logs(user),
        "achievements": achievements,
    }

    if driving_stats:
        context["driving_stats"] = driving_stats
        context["personal_driving_operator_rankings"] = get_personal_driving_operator_rankings(user)
        context["personal_driving_type_rankings"] = get_personal_driving_type_rankings(user)
        context["recent_driving_logs"] = get_recent_driving_logs(user)

    return render(
        request,
        "fleet_completion_public.html",
        context,
    )


def driving_completion(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.is_driver:
        raise PermissionDenied("Driver status required.")

    return render(
        request,
        "driving_completion.html",
        {
            "driving_stats": get_user_driving_stats(request.user),
            "personal_operator_rankings": get_personal_operator_rankings(request.user),
            "personal_type_rankings": get_personal_type_rankings(request.user),
            "overall_operator_rankings": get_overall_operator_rankings(),
            "overall_type_rankings": get_overall_type_rankings(),
        },
    )


def public_driving_completion(request, username):
    user = get_object_or_404(User, username=username)

    if not user.is_driver:
        raise PermissionDenied("This user is not a driver.")
    if not user.driving_logging_public:
        raise PermissionDenied("This user's driving completion is not public.")

    return render(
        request,
        "driving_completion_public.html",
        {
            "profile_user": user,
            "driving_stats": get_user_driving_stats(user),
            "personal_operator_rankings": get_personal_operator_rankings(user),
            "personal_type_rankings": get_personal_type_rankings(user),
            "overall_operator_rankings": get_overall_operator_rankings(),
            "overall_type_rankings": get_overall_type_rankings(),
        },
    )


def transittracker_import(request):
    """
    View for importing ridden logs from TransitTracker.
    Allows superusers to select operators and trigger the import process.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        raise PermissionDenied

    # Get all operators for the selection form (for manual override)
    operators = Operator.objects.filter(vehicle__isnull=False).distinct().order_by('name')

    context = {
        "operators": operators,
    }

    return render(request, "transittracker_import.html", context)


@require_POST
def transittracker_import_run(request):
    """
    API endpoint to run the TransitTracker import.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"error": "Superuser access required"}, status=403)

    transittracker_username = request.POST.get("transittracker_username")
    target_user_id = request.POST.get("target_user")
    operator_nocs = request.POST.getlist("operators")
    datasource = request.POST.get("datasource", "BUSTIM")

    if not transittracker_username:
        return JsonResponse({"error": "TransitTracker username is required"}, status=400)

    if not target_user_id:
        return JsonResponse({"error": "Target user is required"}, status=400)

    if not operator_nocs:
        return JsonResponse({"error": "At least one operator must be selected"}, status=400)

    try:
        target_user = User.objects.get(pk=target_user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Target user not found"}, status=404)

    try:
        # Run the import
        results = run_import(
            transittracker_username=transittracker_username,
            user=target_user,
            operator_nocs=operator_nocs,
            datasource=datasource,
            dry_run=False
        )

        return JsonResponse({
            "success": True,
            "results": results
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


def transittracker_user_search(request):
    """
    API endpoint to search for users.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"error": "Superuser access required"}, status=403)

    query = request.GET.get("q", "")
    if len(query) < 2:
        return JsonResponse({"users": []})

    users = User.objects.filter(
        username__icontains=query
    ).order_by('username')[:10]

    user_list = [
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.get_full_name() or user.username
        }
        for user in users
    ]

    return JsonResponse({"users": user_list})


@require_POST
def transittracker_check_username(request):
    """
    API endpoint to check if a TransitTracker username exists and is public.
    Step 1 of the workflow.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"error": "Superuser access required"}, status=403)

    transittracker_username = request.POST.get("transittracker_username")
    datasource = request.POST.get("datasource", "BUSTIM")

    if not transittracker_username:
        return JsonResponse({"error": "TransitTracker username is required"}, status=400)

    try:
        from fleet.transittracker_scraper import TransitTrackerScraper

        scraper = TransitTrackerScraper(transittracker_username, datasource)
        result = scraper.check_user_exists()

        return JsonResponse({
            "success": True,
            "exists": result["exists"],
            "public": result["public"],
            "error": result["error"]
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@require_POST
def transittracker_get_operators(request):
    """
    API endpoint to get all operators the user has logged on TransitTracker.
    Step 2 of the workflow.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"error": "Superuser access required"}, status=403)

    transittracker_username = request.POST.get("transittracker_username")
    datasource = request.POST.get("datasource", "BUSTIM")

    if not transittracker_username:
        return JsonResponse({"error": "TransitTracker username is required"}, status=400)

    try:
        from fleet.transittracker_scraper import TransitTrackerScraper

        scraper = TransitTrackerScraper(transittracker_username, datasource)
        operator_nocs = scraper.get_operators_from_main_page()

        # Get operator names for display
        operators_with_names = []
        for noc in operator_nocs:
            operator = Operator.objects.filter(noc__iexact=noc).first()
            if operator:
                operators_with_names.append({
                    "noc": noc,
                    "name": operator.name
                })
            else:
                operators_with_names.append({
                    "noc": noc,
                    "name": noc
                })

        return JsonResponse({
            "success": True,
            "operators": operators_with_names
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@require_POST
def transittracker_preview(request):
    """
    API endpoint to preview the import without creating records.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return JsonResponse({"error": "Superuser access required"}, status=403)

    transittracker_username = request.POST.get("transittracker_username")
    target_user_id = request.POST.get("target_user")
    operator_nocs = request.POST.getlist("operators")
    datasource = request.POST.get("datasource", "BUSTIM")

    if not transittracker_username:
        return JsonResponse({"error": "TransitTracker username is required"}, status=400)

    if not target_user_id:
        return JsonResponse({"error": "Target user is required"}, status=400)

    if not operator_nocs:
        return JsonResponse({"error": "At least one operator must be selected"}, status=400)

    try:
        target_user = User.objects.get(pk=target_user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Target user not found"}, status=404)

    try:
        from fleet.transittracker_scraper import TransitTrackerScraper, match_vehicle_to_database, ScrapedVehicle

        scraper = TransitTrackerScraper(transittracker_username, datasource)

        preview_results = {}

        for operator_noc in operator_nocs:
            vehicles = scraper.scrape_operator(operator_noc)

            matched_count = 0
            new_logs_count = 0
            skipped_count = 0

            for vehicle in vehicles:
                db_vehicle = match_vehicle_to_database(vehicle, operator_noc)
                if db_vehicle:
                    matched_count += 1
                    # Check if ride log already exists
                    from fleet.models import FleetRideLog
                    if not FleetRideLog.objects.filter(user=target_user, vehicle=db_vehicle).exists():
                        new_logs_count += 1
                    else:
                        skipped_count += 1
                else:
                    skipped_count += 1

            preview_results[operator_noc] = {
                "vehicles_found": len(vehicles),
                "matched": matched_count,
                "new_logs": new_logs_count,
                "skipped": skipped_count
            }

        total_new_logs = sum(r["new_logs"] for r in preview_results.values())

        return JsonResponse({
            "success": True,
            "preview": preview_results,
            "total_new_logs": total_new_logs
        })

    except Exception as e:
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


def overland_generator(request):
    if (
        not request.user.is_authenticated
        or not request.user.has_perm("fleet.use_overland")
    ):
        raise PermissionDenied("Overland tracking permission required.")

    if request.method == "POST":
        vehicle_slug = request.POST.get("vehicle_slug", "").strip()
        destination = request.POST.get("destination", "").strip()
        route_number = request.POST.get("route_number", "").strip()
        trip_id = request.POST.get("trip_id", "").strip()
        if not vehicle_slug:
            return render(request, "overland_generator.html", {"error": "Select a vehicle."})
        try:
            vehicle = Vehicle.objects.get(slug=vehicle_slug)
        except Vehicle.DoesNotExist:
            return render(request, "overland_generator.html", {"error": "Vehicle not found."})

        import secrets
        auth_key = secrets.token_urlsafe(32)
        subscription = OverlandSubscription.objects.create(
            user=request.user,
            vehicle=vehicle,
            destination=destination,
            route_number=route_number,
            trip_id=trip_id,
            auth_key_hash=OverlandSubscription.hash_auth_key(auth_key),
        )
        from urllib.parse import urlencode
        endpoint = f"https://eeveeit.uk/overland/{subscription.uuid}"
        endpoint += "?" + urlencode({
            "vehicle": vehicle.slug,
            "destination": destination,
            "route": route_number,
            "auth": auth_key,
            "trip": trip_id,
        })
        return render(request, "overland_generator.html", {
            "endpoint": endpoint,
            "vehicle": vehicle,
        })

    return render(request, "overland_generator.html", {})


@csrf_exempt
@require_POST
def overland_ingest(request, uuid):
    subscription = get_object_or_404(OverlandSubscription, uuid=uuid)
    auth_key = request.GET.get("auth", "")
    if not auth_key or not subscription.check_auth_key(auth_key):
        return JsonResponse({"error": "Invalid auth key"}, status=403)

    try:
        payload = json.loads(request.body)
        location = payload["locations"][-1]
        coordinates = location["geometry"]["coordinates"]
        properties = location.get("properties", {})
        longitude, latitude = coordinates
        timestamp = properties.get("timestamp")
        parsed_timestamp = parse_datetime(timestamp) if timestamp else timezone.now()
        if parsed_timestamp is None:
            return JsonResponse({"error": "Invalid timestamp"}, status=400)
        subscription.latitude = latitude
        subscription.longitude = longitude
        heading = properties.get("course") or properties.get("heading")
        subscription.heading = round(float(heading)) if heading is not None else None
        subscription.last_timestamp = parsed_timestamp
        subscription.save(update_fields=["latitude", "longitude", "heading", "last_timestamp", "updated_at"])
        
        # Create or update VehicleJourney for tracking
        from django.core.cache import cache
        vehicle = subscription.vehicle
        
        # Get or create Overland data source
        data_source, _ = DataSource.objects.get_or_create(
            name="Overland",
            defaults={"url": "https://overland.tech"}
        )
        
        # Try to find existing journey for today
        today = parsed_timestamp.date()
        existing_journey = VehicleJourney.objects.filter(
            vehicle=vehicle,
            date=today,
            code__contains=subscription.route_number or ""
        ).first()
        
        if existing_journey:
            # Update existing journey
            existing_journey.datetime = parsed_timestamp
            existing_journey.destination = subscription.destination
            existing_journey.route_name = subscription.route_number or "Overland"
            existing_journey.code = subscription.route_number or "Overland"
            existing_journey.save(update_fields=["datetime", "destination", "route_name", "code"])
            journey_id = existing_journey.id
        else:
            # Create new journey with proper fields for journeys table
            new_journey = VehicleJourney.objects.create(
                vehicle=vehicle,
                datetime=parsed_timestamp,
                date=today,
                destination=subscription.destination,
                code=subscription.route_number or "Overland",
                route_name=subscription.route_number or "Overland",
                source=data_source,
                direction=""
            )
            journey_id = new_journey.id
        
        # Store location data in Redis for map history using the journey's UUID
        journey_obj = VehicleJourney.objects.get(id=journey_id)
        journey_redis_key = journey_obj.get_redis_key()
        location_data = {
            "coordinates": [float(longitude), float(latitude)],
            "datetime": parsed_timestamp.isoformat(),
            "heading": subscription.heading,
            "destination": subscription.destination
        }
        cache.set(journey_redis_key, location_data, timeout=3600)  # 1 hour
        
        # Store multiple location points for tracking trail by appending to a list
        trail_redis_key = f"journey_trail_{journey_id}"
        existing_trail = cache.get(trail_redis_key, [])
        existing_trail.append({
            "coordinates": [float(longitude), float(latitude)],
            "datetime": parsed_timestamp.isoformat(),
            "heading": subscription.heading
        })
        # Keep only last 100 points to avoid memory issues
        if len(existing_trail) > 100:
            existing_trail = existing_trail[-100:]
        cache.set(trail_redis_key, existing_trail, timeout=3600)  # 1 hour
        
        # Update vehicle's latest journey
        vehicle.latest_journey_id = journey_id
        vehicle.save(update_fields=["latest_journey_id"])
        
        # Add vehicle to Redis tracking for "Track this bus" button
        vehicle_redis_key = f"vehicle{vehicle.id}"
        vehicle_data = {
            "journey_id": journey_id,
            "datetime": parsed_timestamp.isoformat(),
            "coordinates": [float(longitude), float(latitude)]
        }
        cache.set(vehicle_redis_key, vehicle_data, timeout=3600)  # 1 hour
            
    except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid Overland payload"}, status=400)

    return JsonResponse({"result": "ok"})


@require_safe
def overland_json(request):
    # This endpoint is deprecated - all data now goes through vehicles.json
    return JsonResponse([], safe=False)


@require_POST
def toggle_pin_operator(request):
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)

    operator_id = request.POST.get("operator_id")
    if not operator_id:
        return JsonResponse({"success": False, "error": "Operator ID required"}, status=400)

    operator = get_object_or_404(Operator, pk=operator_id)

    pinned, created = PinnedOperator.objects.get_or_create(
        user=request.user,
        operator=operator
    )

    if not created:
        pinned.delete()
        return JsonResponse({"success": True, "pinned": False})

    return JsonResponse({"success": True, "pinned": True})
