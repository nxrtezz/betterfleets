from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe
from django.views.decorators.csrf import csrf_exempt

from busstops.models import Operator
from vehicles.models import Vehicle
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
from fleet.models import LiveVehicleLocation, PinnedOperator

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


def manual_tracking_simulation(request):
    """
    View for manual tracking simulation where users can create and control
    simulated vehicle movements using snap-to-road routing.
    """
    if not request.user.is_authenticated:
        raise PermissionDenied

    return render(
        request,
        "manual_tracking_simulation.html",
        {},
    )


def live_location_tracking(request):
    """
    View for live location tracking where users can select a vehicle
    and the site grabs their live location to show as the bus on vehicle tracking.
    """
    if not request.user.is_authenticated:
        raise PermissionDenied

    # Handle POST request to save location
    if request.method == "POST":
        vehicle_id = request.POST.get("vehicle_id")
        latitude = request.POST.get("latitude")
        longitude = request.POST.get("longitude")
        headcode = request.POST.get("headcode", "").strip()
        destination = request.POST.get("destination", "").strip()
        rotation = request.POST.get("rotation", "").strip()
        lateness = request.POST.get("lateness", "").strip()

        if not vehicle_id or not latitude or not longitude:
            return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)

        try:
            vehicle = Vehicle.objects.get(id=vehicle_id)
            # Delete previous live locations for this vehicle
            LiveVehicleLocation.objects.filter(vehicle=vehicle).delete()
            # Create new live location
            LiveVehicleLocation.objects.create(
                vehicle=vehicle,
                latitude=latitude,
                longitude=longitude,
                headcode=headcode,
                destination=destination,
                rotation=int(rotation) if rotation else None,
                lateness=int(lateness) if lateness else None,
            )
            return JsonResponse({"success": True})
        except Vehicle.DoesNotExist:
            return JsonResponse({"success": False, "error": "Vehicle not found"}, status=404)
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    # GET request - show the form
    vehicle_id = request.GET.get("vehicle_id")
    selected_vehicle = None

    if vehicle_id:
        try:
            selected_vehicle = Vehicle.objects.get(id=vehicle_id)
        except Vehicle.DoesNotExist:
            pass

    # Handle vehicle search
    query = request.GET.get("q", "").strip()
    if query and not selected_vehicle:
        from fleet.completion import find_matching_vehicles
        vehicles = find_matching_vehicles(query)
        if vehicles:
            selected_vehicle = vehicles[0]

    context = {
        "selected_vehicle": selected_vehicle,
    }

    return render(
        request,
        "live_location_tracking.html",
        context,
    )


@require_POST
def swap_vehicle_tracking(request):
    """
    Swap live tracking data from one vehicle to another.
    Includes both manual tracking (LiveVehicleLocation) and Bustimes API data (latest_journey_data).
    """
    if not request.user.is_authenticated:
        raise PermissionDenied

    source_vehicle_id = request.POST.get("source_vehicle", "").strip()
    target_vehicle_id = request.POST.get("target_vehicle", "").strip()

    if not source_vehicle_id or not target_vehicle_id:
        return JsonResponse({"success": False, "error": "Missing source or target vehicle"}, status=400)

    try:
        # Find source vehicle by reg, fleet_code, or fleet_number
        source_vehicle = (
            Vehicle.objects.filter(reg__iexact=source_vehicle_id).first()
            or Vehicle.objects.filter(fleet_code__iexact=source_vehicle_id).first()
            or Vehicle.objects.filter(fleet_number=source_vehicle_id).first()
        )
        
        # Find target vehicle by reg, fleet_code, or fleet_number
        target_vehicle = (
            Vehicle.objects.filter(reg__iexact=target_vehicle_id).first()
            or Vehicle.objects.filter(fleet_code__iexact=target_vehicle_id).first()
            or Vehicle.objects.filter(fleet_number=target_vehicle_id).first()
        )

        if not source_vehicle:
            return JsonResponse({"success": False, "error": f"Source vehicle '{source_vehicle_id}' not found"}, status=404)
        
        if not target_vehicle:
            return JsonResponse({"success": False, "error": f"Target vehicle '{target_vehicle_id}' not found"}, status=404)

        # Check for manual tracking data
        source_location = LiveVehicleLocation.objects.filter(vehicle=source_vehicle).first()
        
        # Check for Bustimes API tracking data
        source_journey_data = source_vehicle.latest_journey_data
        
        if not source_location and not source_journey_data:
            return JsonResponse({"success": False, "error": f"Source vehicle '{source_vehicle_id}' has no live tracking data (manual or Bustimes)"}, status=404)

        # Swap manual tracking data if present
        if source_location:
            # Delete existing live location for target vehicle
            LiveVehicleLocation.objects.filter(vehicle=target_vehicle).delete()

            # Create new live location for target vehicle with source's data
            LiveVehicleLocation.objects.create(
                vehicle=target_vehicle,
                latitude=source_location.latitude,
                longitude=source_location.longitude,
                headcode=source_location.headcode,
                destination=source_location.destination,
                rotation=source_location.rotation,
                lateness=source_location.lateness,
            )

        # Swap Bustimes API tracking data if present
        if source_journey_data:
            target_vehicle.latest_journey_data = source_journey_data
            target_vehicle.save()

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


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


@require_safe
def live_tracking_json(request):
    """
    API endpoint for manual live tracking data.
    Returns vehicles tracked via /fleet/live-tracking in the same format as vehicles.json
    """
    from fleet.models import LiveVehicleLocation, ManualTrackingSimulation
    from vehicles.models import Vehicle
    
    locations = []
    
    try:
        # Get all live vehicle locations
        live_locations = LiveVehicleLocation.objects.select_related('vehicle').prefetch_related(
            'vehicle__livery',
            'vehicle__operator',
        ).all()
        
        for live_location in live_locations:
            vehicle = live_location.vehicle
            
            # Build vehicle data in the format expected by VehicleMarker
            vehicle_data = {
                "id": vehicle.id,
                "coordinates": [float(live_location.longitude), float(live_location.latitude)],
                "heading": live_location.rotation,
                "datetime": live_location.created_at.isoformat(),
                "destination": live_location.destination or "",
                "trip_id": None,
                "service_id": None,
                "service": None,
                "operator": {
                    "name": vehicle.operator.name if vehicle.operator else "",
                    "url": vehicle.operator.get_absolute_url() if vehicle.operator else "",
                } if vehicle.operator else None,
                "vehicle": vehicle.get_json(),
                "source": "manual",
                "is_manual": True,  # Marker to identify manually tracked vehicles
            }
            
            # Add delay if available
            if live_location.lateness is not None:
                vehicle_data["delay"] = live_location.lateness
            
            locations.append(vehicle_data)
            
        # Get active manual tracking simulations
        active_simulations = ManualTrackingSimulation.objects.filter(
            is_active=True
        ).select_related('vehicle', 'vehicle__operator').prefetch_related('vehicle__livery')
        
        for simulation in active_simulations:
            vehicle = simulation.vehicle
            position = simulation.current_position
            
            if position:
                vehicle_data = {
                    "id": f"manual_sim_{simulation.id}",
                    "coordinates": [position.get("lng"), position.get("lat")],
                    "heading": position.get("heading"),
                    "datetime": simulation.modified_at.isoformat(),
                    "destination": simulation.name,
                    "trip_id": None,
                    "service_id": simulation.service.id if simulation.service else None,
                    "service": {
                        "url": simulation.service.get_absolute_url() if simulation.service else "",
                        "line_name": simulation.service.line_name if simulation.service else "",
                    } if simulation.service else None,
                    "operator": {
                        "name": vehicle.operator.name if vehicle.operator else "",
                        "url": vehicle.operator.get_absolute_url() if vehicle.operator else "",
                    } if vehicle.operator else None,
                    "vehicle": vehicle.get_json(),
                    "source": "manual_simulation",
                    "is_manual": True,
                    "simulation_id": simulation.id,
                }
                locations.append(vehicle_data)
                
    except Exception as e:
        logging.error("Error fetching manual tracking data: %s", e)
        locations = []
    
    response = JsonResponse(locations, safe=False)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    
    return response


@require_safe
def vehicle_search_json(request):
    """
    API endpoint for searching vehicles by registration, fleet number, or code.
    Returns JSON results for use in vehicle selection forms.
    """
    query = request.GET.get("q", "").strip()
    operator_id = request.GET.get("operator_id")
    
    vehicles = Vehicle.objects.select_related('operator', 'livery')
    
    if operator_id:
        vehicles = vehicles.filter(operator_id=operator_id)
    
    if query:
        vehicles = vehicles.filter(
            Q(registration__icontains=query) |
            Q(fleet_number__icontains=query) |
            Q(fleet_code__icontains=query) |
            Q(code__icontains=query)
        )
    
    vehicles = vehicles[:50]
    
    results = []
    for vehicle in vehicles:
        results.append({
            "id": vehicle.id,
            "registration": vehicle.registration or "",
            "fleet_number": vehicle.fleet_number or "",
            "fleet_code": vehicle.fleet_code or "",
            "code": vehicle.code or "",
            "name": str(vehicle),
            "operator": vehicle.operator.name if vehicle.operator else "",
            "operator_id": vehicle.operator.id if vehicle.operator else None,
            "url": vehicle.get_absolute_url(),
        })
    
    return JsonResponse(results, safe=False)


@require_POST
def create_manual_simulation(request):
    """
    Create a new manual tracking simulation route.
    
    Accepts JSON payload with:
    - vehicle_id: ID of the vehicle to simulate
    - name: Name for the simulation
    - route_type: 'stops' or 'service'
    - stops: List of stop coordinates (for stop-based routes)
    - service_id: Service ID (for service-based routes)
    - direction: 'inbound' or 'outbound' (for service-based routes)
    - speed_multiplier: Speed multiplier (default 1.0)
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)
    
    try:
        import json
        data = json.loads(request.body)
    except:
        data = request.POST
    
    vehicle_id = data.get("vehicle_id")
    name = data.get("name")
    route_type = data.get("route_type", "stops")
    speed_multiplier = data.get("speed_multiplier", 1.0)
    
    if not vehicle_id or not name:
        return JsonResponse({"success": False, "error": "Missing required fields"}, status=400)
    
    try:
        vehicle = Vehicle.objects.get(id=vehicle_id)
    except Vehicle.DoesNotExist:
        return JsonResponse({"success": False, "error": "Vehicle not found"}, status=404)
    
    # Create simulation
    simulation = ManualTrackingSimulation(
        vehicle=vehicle,
        name=name,
        route_type=route_type,
        speed_multiplier=float(speed_multiplier),
        created_by=request.user,
    )
    
    # Handle route type specific data
    if route_type == "service":
        service_id = data.get("service_id")
        direction = data.get("direction")
        
        if not service_id:
            return JsonResponse({"success": False, "error": "service_id required for service-based routes"}, status=400)
        
        from busstops.models import Service
        try:
            service = Service.objects.get(id=service_id)
            simulation.service = service
            simulation.direction = direction
            
            # Get stops from service route
            # This will be processed asynchronously to fetch OSRM route
        except Service.DoesNotExist:
            return JsonResponse({"success": False, "error": "Service not found"}, status=404)
            
    elif route_type == "stops":
        stops = data.get("stops", [])
        if not stops or len(stops) < 2:
            return JsonResponse({"success": False, "error": "At least 2 stops required for stop-based routes"}, status=400)
        
        simulation.stops = stops
    
    simulation.save()
    
    # Trigger OSRM route calculation asynchronously
    # This will be handled by a background task or on next request
    
    return JsonResponse({
        "success": True,
        "simulation_id": simulation.id,
        "message": "Simulation created. Route calculation will be processed."
    })


@require_POST
def update_manual_simulation(request, simulation_id):
    """
    Update an existing manual tracking simulation.
    
    Can update:
    - is_active: Start/stop simulation
    - progress: Set progress (0.0 to 1.0)
    - speed_multiplier: Change speed
    - current_position: Manual position update
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)
    
    try:
        import json
        data = json.loads(request.body)
    except:
        data = request.POST
    
    try:
        simulation = ManualTrackingSimulation.objects.get(id=simulation_id)
    except ManualTrackingSimulation.DoesNotExist:
        return JsonResponse({"success": False, "error": "Simulation not found"}, status=404)
    
    # Update fields
    if "is_active" in data:
        simulation.is_active = bool(data["is_active"])
        if simulation.is_active and not simulation.started_at:
            simulation.started_at = timezone.now()
    
    if "progress" in data:
        simulation.progress = float(data["progress"])
    
    if "speed_multiplier" in data:
        simulation.speed_multiplier = float(data["speed_multiplier"])
    
    if "current_position" in data:
        simulation.current_position = data["current_position"]
    
    simulation.save()
    
    return JsonResponse({"success": True, "simulation_id": simulation.id})


@require_POST
def calculate_simulation_route(request, simulation_id):
    """
    Calculate OSRM route for a simulation.
    
    This endpoint triggers OSRM routing for the simulation's stops
    and stores the route geometry and segments with speed limits.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)
    
    try:
        simulation = ManualTrackingSimulation.objects.get(id=simulation_id)
    except ManualTrackingSimulation.DoesNotExist:
        return JsonResponse({"success": False, "error": "Simulation not found"}, status=404)
    
    # Get OSRM server URL from settings
    osrm_url = getattr(settings, 'OSRM_SERVER_URL', 'http://localhost:5000')
    
    try:
        # Build coordinates from stops
        if simulation.route_type == "stops":
            coordinates = ";".join([f"{s['lng']},{s['lat']}" for s in simulation.stops])
        elif simulation.route_type == "service" and simulation.service:
            # Get stops from service
            from bustimes.models import Route, Trip, StopTime
            route = Route.objects.filter(service=simulation.service).first()
            if route:
                # Get a trip for the correct direction
                trip = Trip.objects.filter(
                    route=route,
                    inbound=(simulation.direction == "inbound")
                ).first()
                if trip:
                    stop_times = trip.stoptime_set.select_related('stop').order_by('sequence')
                    coordinates = ";".join([
                        f"{st.stop.longitude},{st.stop.latitude}" 
                        for st in stop_times if st.stop and st.stop.location
                    ])
                else:
                    return JsonResponse({"success": False, "error": "No trip found for service/direction"}, status=400)
            else:
                return JsonResponse({"success": False, "error": "No route found for service"}, status=400)
        else:
            return JsonResponse({"success": False, "error": "No stops available for routing"}, status=400)
        
        # Call OSRM
        import requests
        osrm_response = requests.get(
            f"{osrm_url}/route/v1/driving/{coordinates}?overview=full&geometries=geojson",
            timeout=30
        )
        
        if osrm_response.status_code != 200:
            return JsonResponse({"success": False, "error": f"OSRM request failed: {osrm_response.status_code}"}, status=500)
        
        osrm_data = osrm_response.json()
        
        if osrm_data.get("code") != "Ok":
            return JsonResponse({"success": False, "error": f"OSRM error: {osrm_data.get('code')}"}, status=500)
        
        # Store route geometry
        route = osrm_data["routes"][0]
        simulation.route_geometry = route["geometry"]
        
        # Calculate segments with speed limits
        # For now, use OSRM's segment data with default speed limits
        # In future, integrate with road speed limit data
        simulation.route_segments = []
        simulation.save()
        
        return JsonResponse({
            "success": True,
            "distance": route["distance"],
            "duration": route["duration"],
            "message": "Route calculated successfully"
        })
        
    except requests.RequestException as e:
        return JsonResponse({"success": False, "error": f"OSRM request failed: {str(e)}"}, status=500)
    except Exception as e:
        logging.error("Error calculating simulation route: %s", e)
        return JsonResponse({"success": False, "error": str(e)}, status=500)
