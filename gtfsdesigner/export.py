import zipfile
import io
from datetime import datetime
from django.http import HttpResponse
from . import models


def generate_gtfs_zip(project):
    """Export a GTFS project as a ZIP file"""
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # agency.txt
        agency_content = generate_agency_txt(project)
        zip_file.writestr('agency.txt', agency_content)

        # stops.txt
        stops_content = generate_stops_txt(project)
        zip_file.writestr('stops.txt', stops_content)

        # routes.txt
        routes_content = generate_routes_txt(project)
        zip_file.writestr('routes.txt', routes_content)

        # trips.txt
        trips_content = generate_trips_txt(project)
        zip_file.writestr('trips.txt', trips_content)

        # stop_times.txt
        stop_times_content = generate_stop_times_txt(project)
        zip_file.writestr('stop_times.txt', stop_times_content)

        # calendar.txt
        calendar_content = generate_calendar_txt(project)
        zip_file.writestr('calendar.txt', calendar_content)

        # calendar_dates.txt
        calendar_dates_content = generate_calendar_dates_txt(project)
        zip_file.writestr('calendar_dates.txt', calendar_dates_content)

    zip_buffer.seek(0)
    return zip_buffer


def generate_agency_txt(project):
    """Generate agency.txt content"""
    lines = ['agency_id,agency_name,agency_url,agency_timezone,agency_lang,agency_phone,agency_email,agency_fare_url']

    for operator in project.operators.all():
        line = f"{operator.noc},{operator.name},{operator.url},{operator.timezone},{operator.lang},{operator.phone},{operator.email},{operator.fare_url}"
        lines.append(line)

    return '\n'.join(lines)


def generate_stops_txt(project):
    """Generate stops.txt content"""
    lines = ['stop_id,stop_code,stop_name,stop_lat,stop_lon,stop_url,location_type,parent_station,stop_timezone,wheelchair_boarding,platform_code']

    for stop in project.stops.all():
        line = f"{stop.stop_id},{stop.stop_code},{stop.stop_name},{stop.stop_lat},{stop.stop_lon},{stop.stop_url},{stop.location_type},{stop.parent_station.stop_id if stop.parent_station else ''},{stop.stop_timezone},{stop.wheelchair_boarding},{stop.platform_code}"
        lines.append(line)

    return '\n'.join(lines)


def generate_routes_txt(project):
    """Generate routes.txt content"""
    lines = ['route_id,agency_id,route_short_name,route_long_name,route_desc,route_type,route_url,route_color,route_text_color,continuous_pickup,continuous_drop_off']

    for route in project.routes.all():
        line = f"{route.route_id},{route.agency_id},{route.route_short_name},{route.route_long_name},{route.route_desc},{route.route_type},{route.route_url},{route.route_color},{route.route_text_color},{route.continuous_pickup or ''},{route.continuous_drop_off or ''}"
        lines.append(line)

    return '\n'.join(lines)


def generate_trips_txt(project):
    """Generate trips.txt content"""
    lines = ['route_id,service_id,trip_id,trip_headsign,trip_short_name,direction_id,block_id,shape_id,wheelchair_accessible,bikes_allowed']

    for trip in project.trips.all():
        line = f"{trip.route.route_id},{trip.service_id},{trip.trip_id},{trip.trip_headsign},{trip.trip_short_name},{trip.direction_id or ''},{trip.block_id or ''},{trip.shape_id or ''},{trip.wheelchair_accessible},{trip.bikes_allowed}"
        lines.append(line)

    return '\n'.join(lines)


def generate_stop_times_txt(project):
    """Generate stop_times.txt content"""
    lines = ['trip_id,arrival_time,departure_time,stop_id,stop_sequence,stop_headsign,pickup_type,drop_off_type,shape_dist_traveled,timepoint']

    for trip in project.trips.all():
        for trip_stop in trip.trip_stops.all().order_by('sequence'):
            timing = trip_stop.timings.first() if hasattr(trip_stop, 'timings') else None

            arrival_time = timing.arrival_time.strftime('%H:%M:%S') if timing and timing.arrival_time else ''
            departure_time = timing.departure_time.strftime('%H:%M:%S') if timing and timing.departure_time else ''
            stop_headsign = timing.stop_headsign if timing else ''
            pickup_type = timing.pickup_type if timing else trip_stop.pickup_type
            drop_off_type = timing.drop_off_type if timing else trip_stop.drop_off_type
            shape_dist_traveled = timing.shape_dist_traveled if timing else ''
            timepoint = timing.timepoint if timing else trip_stop.timepoint

            line = f"{trip.trip_id},{arrival_time},{departure_time},{trip_stop.stop.stop_id},{trip_stop.sequence},{stop_headsign},{pickup_type},{drop_off_type},{shape_dist_traveled},{timepoint}"
            lines.append(line)

    return '\n'.join(lines)


def generate_calendar_txt(project):
    """Generate calendar.txt content"""
    lines = ['service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date']

    for calendar in project.calendars.all():
        line = f"{calendar.service_id},{int(calendar.monday)},{int(calendar.tuesday)},{int(calendar.wednesday)},{int(calendar.thursday)},{int(calendar.friday)},{int(calendar.saturday)},{int(calendar.sunday)},{calendar.start_date.strftime('%Y%m%d')},{calendar.end_date.strftime('%Y%m%d') if calendar.end_date else ''}"
        lines.append(line)

    return '\n'.join(lines)


def generate_calendar_dates_txt(project):
    """Generate calendar_dates.txt content"""
    lines = ['service_id,date,exception_type']

    for calendar_date in project.calendar_dates.all():
        line = f"{calendar_date.service_id},{calendar_date.date.strftime('%Y%m%d')},{calendar_date.exception_type}"
        lines.append(line)

    return '\n'.join(lines)
