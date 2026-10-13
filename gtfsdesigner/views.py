from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from busstops.models import StopPoint
from . import models
from .export import generate_gtfs_zip


def superuser_required(view_func):
    """Decorator to require superuser access"""
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped_view


@login_required
@superuser_required
def index(request):
    """List all GTFS projects"""
    projects = models.GTFSProject.objects.filter(created_by=request.user).order_by('-created_at')
    return render(request, 'gtfsdesigner/index.html', {'projects': projects})


@login_required
@superuser_required
def create_project(request):
    """Create a new GTFS project"""
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            project = models.GTFSProject.objects.create(name=name, created_by=request.user)
            return redirect('gtfsdesigner:project_detail', project_id=project.id)
    return render(request, 'gtfsdesigner/create_project.html')


@login_required
@superuser_required
def project_detail(request, project_id):
    """Show project detail with operators, routes, etc."""
    project = get_object_or_404(models.GTFSProject, id=project_id, created_by=request.user)
    operators = project.operators.all()
    routes = project.routes.all()
    calendars = project.calendars.all()
    stops = project.stops.all()
    trips = project.trips.all()

    return render(request, 'gtfsdesigner/project_detail.html', {
        'project': project,
        'operators': operators,
        'routes': routes,
        'calendars': calendars,
        'stops': stops,
        'trips': trips,
    })


@login_required
@superuser_required
def create_operator(request, project_id):
    """Create a new GTFS operator (agency)"""
    project = get_object_or_404(models.GTFSProject, id=project_id, created_by=request.user)

    if request.method == 'POST':
        operator = models.GTFSOperator.objects.create(
            project=project,
            name=request.POST.get('name'),
            noc=request.POST.get('noc'),
            url=request.POST.get('url', ''),
            timezone=request.POST.get('timezone', 'Europe/London'),
            lang=request.POST.get('lang', 'en'),
            phone=request.POST.get('phone', ''),
            email=request.POST.get('email', ''),
            fare_url=request.POST.get('fare_url', ''),
        )
        return redirect('gtfsdesigner:project_detail', project_id=project.id)

    return render(request, 'gtfsdesigner/create_operator.html', {'project': project})


@login_required
@superuser_required
def create_route(request, project_id):
    """Create a new GTFS route"""
    project = get_object_or_404(models.GTFSProject, id=project_id, created_by=request.user)
    operators = project.operators.all()

    if request.method == 'POST':
        route = models.GTFSRoute.objects.create(
            project=project,
            operator_id=request.POST.get('operator'),
            route_id=request.POST.get('route_id'),
            agency_id=request.POST.get('agency_id', ''),
            route_short_name=request.POST.get('route_short_name'),
            route_long_name=request.POST.get('route_long_name', ''),
            route_desc=request.POST.get('route_desc', ''),
            route_type=int(request.POST.get('route_type', 3)),
            route_url=request.POST.get('route_url', ''),
            route_color=request.POST.get('route_color', ''),
            route_text_color=request.POST.get('route_text_color', 'FFFFFF'),
        )
        return redirect('gtfsdesigner:route_detail', route_id=route.id)

    return render(request, 'gtfsdesigner/create_route.html', {
        'project': project,
        'operators': operators,
    })


@login_required
@superuser_required
def route_detail(request, route_id):
    """Show route detail with stop selection and timetable options"""
    route = get_object_or_404(models.GTFSRoute, id=route_id, project__created_by=request.user)
    project = route.project

    # Get inbound and outbound stops
    inbound_stops = route.route_stops.filter(direction=1).order_by('sequence')
    outbound_stops = route.route_stops.filter(direction=0).order_by('sequence')

    # Get calendars
    calendars = project.calendars.all()

    return render(request, 'gtfsdesigner/route_detail.html', {
        'project': project,
        'route': route,
        'inbound_stops': inbound_stops,
        'outbound_stops': outbound_stops,
        'calendars': calendars,
    })


@login_required
@superuser_required
def select_stops(request, route_id, direction):
    """Select stops for a route (inbound or outbound)"""
    route = get_object_or_404(models.GTFSRoute, id=route_id, project__created_by=request.user)
    project = route.project

    # Get existing stops for this direction
    existing_route_stops = route.route_stops.filter(direction=direction).order_by('sequence')

    # Get all stops in the project
    all_stops = project.stops.all()

    # Get some pre-existing stops from StopPoint database for the map
    from busstops.models import StopPoint
    # Get stops near the project or just get some recent ones
    preexisting_stops = StopPoint.objects.filter(active=True).select_related('locality')[:100]

    # Prepare preexisting stops data for template
    preexisting_stops_data = []
    for stop in preexisting_stops:
        preexisting_stops_data.append({
            'id': stop.atco_code,
            'name': stop.common_name,
            'naptan_code': stop.naptan_code or '',
            'locality': stop.locality.name if stop.locality else '',
            'lat': stop.latlong.y if stop.latlong else 0,
            'lon': stop.latlong.x if stop.latlong else 0,
        })

    return render(request, 'gtfsdesigner/select_stops.html', {
        'project': project,
        'route': route,
        'direction': direction,
        'existing_route_stops': existing_route_stops,
        'all_stops': all_stops,
        'preexisting_stops': preexisting_stops_data,
    })


@login_required
@superuser_required
def save_stops(request, route_id, direction):
    """Save selected stops for a route"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    route = get_object_or_404(models.GTFSRoute, id=route_id, project__created_by=request.user)
    stops_data = request.POST.get('stops')  # JSON array of stop data

    if not stops_data:
        return JsonResponse({'error': 'Missing stops data'}, status=400)

    import json
    stops = json.loads(stops_data)

    # Delete existing stops for this direction
    models.RouteStop.objects.filter(route=route, direction=direction).delete()

    # Create new RouteStop records
    for index, stop_data in enumerate(stops):
        # Handle different stop types
        if stop_data.get('type') == 'preexisting':
            # Preexisting stop from StopPoint database - create GTFSStop
            from busstops.models import StopPoint
            stop_point = get_object_or_404(StopPoint, atco_code=stop_data['stop_id'])

            # Check if GTFSStop already exists for this StopPoint
            gtfs_stop, created = models.GTFSStop.objects.get_or_create(
                project=route.project,
                stop_id=stop_data['stop_id'],
                defaults={
                    'stop_name': stop_data['name'],
                    'stop_lat': stop_data['lat'],
                    'stop_lon': stop_data['lon'],
                    'existing_stop': stop_point
                }
            )
            # Update name if it changed
            if not created and gtfs_stop.stop_name != stop_data['name']:
                gtfs_stop.stop_name = stop_data['name']
                gtfs_stop.save()

            stop = gtfs_stop
        else:
            # New or existing GTFSStop
            if stop_data.get('id'):
                stop = get_object_or_404(models.GTFSStop, id=stop_data['id'], project=route.project)
            else:
                # Create new GTFSStop
                stop = models.GTFSStop.objects.create(
                    project=route.project,
                    stop_id=stop_data['stop_id'],
                    stop_name=stop_data['name'],
                    stop_lat=stop_data['lat'],
                    stop_lon=stop_data['lon']
                )

        models.RouteStop.objects.create(
            route=route,
            stop=stop,
            direction=direction,
            sequence=index + 1
        )

    return JsonResponse({'success': True, 'stops_count': len(stops)})


@login_required
@superuser_required
def create_calendar(request, project_id):
    """Create a calendar for service days"""
    project = get_object_or_404(models.GTFSProject, id=project_id, created_by=request.user)

    if request.method == 'POST':
        calendar = models.GTFSCalendar.objects.create(
            project=project,
            service_id=request.POST.get('service_id'),
            monday='monday' in request.POST,
            tuesday='tuesday' in request.POST,
            wednesday='wednesday' in request.POST,
            thursday='thursday' in request.POST,
            friday='friday' in request.POST,
            saturday='saturday' in request.POST,
            sunday='sunday' in request.POST,
            start_date=request.POST.get('start_date'),
            end_date=request.POST.get('end_date') or None,
        )
        return redirect('gtfsdesigner:project_detail', project_id=project.id)

    return render(request, 'gtfsdesigner/create_calendar.html', {'project': project})


@login_required
@superuser_required
def timetable_builder(request, route_id, direction):
    """Build timetables in a spreadsheet-like interface"""
    route = get_object_or_404(models.GTFSRoute, id=route_id, project__created_by=request.user)
    project = route.project
    calendar_id = request.GET.get('calendar_id')

    if calendar_id:
        calendar = get_object_or_404(models.GTFSCalendar, id=calendar_id, project=project)
    else:
        calendar = None

    # Get stops for this direction
    route_stops = route.route_stops.filter(direction=direction).order_by('sequence')

    # Get existing trips for this route, direction, and calendar
    trips = []
    if calendar:
        trips = project.trips.filter(route=route, service_id=calendar.service_id, direction_id=direction)

    return render(request, 'gtfsdesigner/timetable_builder.html', {
        'project': project,
        'route': route,
        'direction': direction,
        'calendar': calendar,
        'route_stops': route_stops,
        'trips': trips,
    })


@login_required
@superuser_required
def save_timetable(request, route_id, direction):
    """Save timetable data"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    route = get_object_or_404(models.GTFSRoute, id=route_id, project__created_by=request.user)
    calendar_id = request.POST.get('calendar_id')
    trips_data = request.POST.get('trips')  # JSON array of trip data

    if not calendar_id or not trips_data:
        return JsonResponse({'error': 'Missing required fields'}, status=400)

    import json
    trips = json.loads(trips_data)

    # TODO: Save trips to database
    # This would involve creating GFSTrip, GFSTripStop, and GFSTripTiming records

    return JsonResponse({'success': True, 'trips_count': len(trips)})


@login_required
@superuser_required
def export_gtfs(request, project_id):
    """Export GTFS data as a ZIP file"""
    project = get_object_or_404(models.GTFSProject, id=project_id, created_by=request.user)

    zip_buffer = generate_gtfs_zip(project)

    response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{project.name.replace(" ", "_")}_gtfs.zip"'

    return response


@login_required
@superuser_required
def search_stops(request):
    """API endpoint to search for existing stops"""
    query = request.GET.get('q', '')
    if len(query) < 2:
        return JsonResponse({'stops': []})

    stops = StopPoint.objects.filter(
        Q(common_name__icontains=query) |
        Q(atco_code__icontains=query) |
        Q(naptan_code__icontains=query)
    ).select_related('locality', 'admin_area')[:20]

    results = []
    for stop in stops:
        results.append({
            'id': stop.atco_code,
            'name': stop.common_name,
            'naptan_code': stop.naptan_code,
            'locality': stop.locality.name if stop.locality else '',
            'latlong': [stop.latlong.y if stop.latlong else None, stop.latlong.x if stop.latlong else None],
        })

    return JsonResponse({'stops': results})


@login_required
@superuser_required
def create_stop(request):
    """API endpoint to create a new stop"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    project_id = request.POST.get('project_id')
    project = get_object_or_404(models.GTFSProject, id=project_id, created_by=request.user)

    stop = models.GTFSStop.objects.create(
        project=project,
        stop_id=request.POST.get('stop_id'),
        stop_code=request.POST.get('stop_code', ''),
        stop_name=request.POST.get('stop_name'),
        stop_lat=float(request.POST.get('stop_lat')),
        stop_lon=float(request.POST.get('stop_lon')),
        stop_url=request.POST.get('stop_url', ''),
        location_type=int(request.POST.get('location_type', 0)),
        stop_timezone=request.POST.get('stop_timezone', ''),
        wheelchair_boarding=int(request.POST.get('wheelchair_boarding', 0)),
        platform_code=request.POST.get('platform_code', ''),
    )

    return JsonResponse({
        'id': stop.id,
        'stop_id': stop.stop_id,
        'stop_name': stop.stop_name,
        'stop_lat': stop.stop_lat,
        'stop_lon': stop.stop_lon,
    })
