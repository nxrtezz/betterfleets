import csv
import logging
from pathlib import Path
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count
from django.utils.dateparse import parse_duration
from django.utils import timezone

from busstops.models import DataSource, Operator, Region, Service, StopPoint
from bustimes.models import Route, Trip, StopTime, Calendar

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import UK National Rail GTFS data with service deduplication."

    def add_arguments(self, parser):
        parser.add_argument(
            "--gtfs-path",
            required=True,
            help="Path to GTFS directory containing txt files.",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Remove previously imported rail services and rebuild from scratch.",
        )

    def handle(self, *args, **options):
        gtfs_path = Path(options["gtfs_path"])
        if not gtfs_path.exists():
            raise CommandError(f"GTFS path not found: {gtfs_path}")

        if options["purge"]:
            self.purge_existing_data()

        self.stdout.write("Reading operators...")
        operators = self.read_operators(gtfs_path)
        self.stdout.write(f"Found {len(operators)} operators")

        self.stdout.write("Reading stations...")
        stations = self.read_stations(gtfs_path)
        self.stdout.write(f"Found {len(stations)} stations")

        self.stdout.write("Reading trips...")
        trips = self.read_trips(gtfs_path)
        self.stdout.write(f"Found {len(trips)} trips")

        self.stdout.write("Reading stop_times...")
        trip_stop_times = self.read_stop_times(gtfs_path)
        self.stdout.write(f"Found {len(trip_stop_times)} trip stop times")

        self.stdout.write("Reading calendars...")
        calendars = self.read_calendars(gtfs_path)
        self.stdout.write(f"Found {len(calendars)} calendars")

        self.stdout.write("Generating services...")
        services = self.generate_services(operators, stations, trips, trip_stop_times)
        self.stdout.write(f"Services created: {len(services)}")

        self.stdout.write("Generating timetables...")
        timetable_count = self.generate_timetables(
            services, trips, trip_stop_times, calendars
        )
        self.stdout.write(f"Timetable entries created: {timetable_count}")

        self.stdout.write("Generating calling patterns...")
        calling_points_count = self.generate_calling_patterns(
            services, trips, trip_stop_times, stations
        )
        self.stdout.write(f"Calling points created: {calling_points_count}")

        self.stdout.write(self.style.SUCCESS("Import complete."))

    def purge_existing_data(self):
        """Remove previously imported rail services and related data."""
        self.stdout.write("Purging existing rail services...")
        
        # Get the rail data source
        try:
            source = DataSource.objects.get(name="National Rail GTFS")
        except DataSource.DoesNotExist:
            self.stdout.write("No existing rail data source found.")
            return

        # Delete related data in order
        with transaction.atomic():
            # Delete stop times for rail trips
            rail_trips = Trip.objects.filter(route__source=source)
            StopTime.objects.filter(trip__in=rail_trips).delete()
            
            # Delete rail trips
            rail_trips.delete()
            
            # Delete rail routes
            Route.objects.filter(source=source).delete()
            
            # Delete rail services
            Service.objects.filter(source=source).delete()
            
            # Delete the source
            source.delete()

        self.stdout.write("Purge complete.")

    def read_operators(self, gtfs_path):
        """Read agency.txt and map to existing Operator records."""
        operators = {}
        agency_file = gtfs_path / "agency.txt"
        
        if not agency_file.exists():
            raise CommandError("agency.txt not found in GTFS path")

        with open(agency_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                agency_id = row["agency_id"]
                agency_name = row["agency_name"]
                
                # Try to find existing operator by name or NOC
                operator = Operator.objects.filter(
                    name__iexact=agency_name
                ).first()
                
                if not operator:
                    # Try to match by agency_id as NOC
                    operator = Operator.objects.filter(
                        noc__iexact=agency_id
                    ).first()
                
                if not operator:
                    # Create new operator
                    operator = Operator.objects.create(
                        noc=agency_id[:10],  # NOC max length is 10
                        name=agency_name,
                        vehicle_mode="rail",
                    )
                    self.stdout.write(f"Created new operator: {operator.name} ({operator.noc})")
                
                operators[agency_id] = operator

        return operators

    def read_stations(self, gtfs_path):
        """Read stops.txt and create/update StopPoint records."""
        stations = {}
        stops_file = gtfs_path / "stops.txt"
        
        if not stops_file.exists():
            raise CommandError("stops.txt not found in GTFS path")

        # Get or create data source
        source, _ = DataSource.objects.get_or_create(
            name="National Rail GTFS",
            defaults={"url": ""}
        )

        with open(stops_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stop_id = row["stop_id"]
                stop_name = row["stop_name"]
                
                # Extract CRS code if available
                crs_code = row.get("stop_code", "")
                
                # Create or update stop
                atco_code = f"rail-{stop_id}"
                stop, created = StopPoint.objects.update_or_create(
                    atco_code=atco_code,
                    defaults={
                        "common_name": stop_name[:48],
                        "crs_code": crs_code[:3] if crs_code else None,
                        "stop_type": "RPL",
                        "active": True,
                        "source": source,
                    }
                )
                
                stations[stop_id] = {
                    "stop": stop,
                    "name": stop_name,
                    "crs": crs_code,
                }

        return stations

    def read_trips(self, gtfs_path):
        """Read trips.txt and return trip data."""
        trips = {}
        trips_file = gtfs_path / "trips.txt"
        
        if not trips_file.exists():
            raise CommandError("trips.txt not found in GTFS path")

        with open(trips_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row["trip_id"]
                route_id = row["route_id"]
                service_id = row["service_id"]
                agency_id = row.get("agency_id", "")
                
                trips[trip_id] = {
                    "route_id": route_id,
                    "service_id": service_id,
                    "agency_id": agency_id,
                }

        return trips

    def read_stop_times(self, gtfs_path):
        """Read stop_times.txt and organize by trip."""
        trip_stop_times = defaultdict(list)
        stop_times_file = gtfs_path / "stop_times.txt"
        
        if not stop_times_file.exists():
            raise CommandError("stop_times.txt not found in GTFS path")

        with open(stop_times_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row["trip_id"]
                trip_stop_times[trip_id].append({
                    "stop_id": row["stop_id"],
                    "stop_sequence": int(row["stop_sequence"]),
                    "arrival_time": row["arrival_time"],
                    "departure_time": row["departure_time"],
                })

        # Sort stop times by sequence for each trip
        for trip_id in trip_stop_times:
            trip_stop_times[trip_id].sort(key=lambda x: x["stop_sequence"])

        return trip_stop_times

    def read_calendars(self, gtfs_path):
        """Read calendar.txt and calendar_dates.txt."""
        calendars = {}
        calendar_file = gtfs_path / "calendar.txt"
        
        if calendar_file.exists():
            with open(calendar_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    service_id = row["service_id"]
                    calendars[service_id] = {
                        "monday": row["monday"] == "1",
                        "tuesday": row["tuesday"] == "1",
                        "wednesday": row["wednesday"] == "1",
                        "thursday": row["thursday"] == "1",
                        "friday": row["friday"] == "1",
                        "saturday": row["saturday"] == "1",
                        "sunday": row["sunday"] == "1",
                        "start_date": row["start_date"],
                        "end_date": row.get("end_date", ""),
                    }

        # Read calendar_dates.txt for exceptions
        calendar_dates_file = gtfs_path / "calendar_dates.txt"
        if calendar_dates_file.exists():
            with open(calendar_dates_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    service_id = row["service_id"]
                    if service_id not in calendars:
                        calendars[service_id] = {
                            "monday": False, "tuesday": False, "wednesday": False,
                            "thursday": False, "friday": False, "saturday": False,
                            "sunday": False, "start_date": "", "end_date": "",
                        }
                    # Store exception dates (could be used for more complex logic)
                    calendars[service_id]["exceptions"] = calendars[service_id].get("exceptions", [])
                    calendars[service_id]["exceptions"].append({
                        "date": row["date"],
                        "exception_type": row["exception_type"],  # 1 = added, 2 = removed
                    })

        return calendars

    def generate_services(self, operators, stations, trips, trip_stop_times):
        """Generate services with deduplication based on (operator, origin_crs, destination_crs)."""
        # Get or create data source
        source, _ = DataSource.objects.get_or_create(
            name="National Rail GTFS",
            defaults={"url": ""}
        )

        # Build service key to track deduplication
        service_keys = {}  # (operator_id, origin_crs, destination_crs) -> service
        services = {}  # service_id -> Service object
        operator_service_counts = defaultdict(int)

        # Process each trip to generate services
        for trip_id, trip_data in trips.items():
            agency_id = trip_data["agency_id"]
            operator = operators.get(agency_id)
            
            if not operator:
                continue

            # Get stop times for this trip
            stop_times = trip_stop_times.get(trip_id, [])
            if not stop_times:
                continue

            # Get origin and destination stations
            first_stop = stop_times[0]
            last_stop = stop_times[-1]
            
            origin_station = stations.get(first_stop["stop_id"])
            destination_station = stations.get(last_stop["stop_id"])
            
            if not origin_station or not destination_station:
                continue

            origin_crs = origin_station["crs"] or first_stop["stop_id"]
            destination_crs = destination_station["crs"] or last_stop["stop_id"]
            origin_name = origin_station["name"]
            destination_name = destination_station["name"]

            # Build unique key
            service_key = (operator.id, origin_crs, destination_crs)

            # Check if service already exists
            if service_key not in service_keys:
                # Create new service
                line_name = f"{origin_crs} - {destination_crs}"
                description = f"{origin_name} - {destination_name}"
                
                service = Service.objects.create(
                    line_name=line_name,
                    description=description,
                    mode="rail",
                    current=True,
                    source=source,
                )
                service.operator.add(operator)
                
                service_keys[service_key] = service
                services[trip_data["service_id"]] = service
                operator_service_counts[operator.name] += 1
            else:
                # Use existing service
                service = service_keys[service_key]
                services[trip_data["service_id"]] = service

        # Log operator service counts
        for operator_name, count in sorted(operator_service_counts.items()):
            self.stdout.write(f"{operator_name}: {count} services")

        return services

    def generate_timetables(self, services, trips, trip_stop_times, calendars):
        """Generate timetable entries (trips) linked to services."""
        # Get or create data source
        source, _ = DataSource.objects.get_or_create(
            name="National Rail GTFS",
            defaults={"url": ""}
        )

        # Create routes for each service
        routes = {}
        for service_id, service in services.items():
            route, _ = Route.objects.get_or_create(
                source=source,
                code=service_id,
                defaults={
                    "service": service,
                    "line_name": service.line_name,
                    "description": service.description,
                }
            )
            routes[service_id] = route

        # Create trips
        trips_to_create = []
        trip_map = {}  # trip_id -> Trip object

        for trip_id, trip_data in trips.items():
            service_id = trip_data["service_id"]
            service = services.get(service_id)
            route = routes.get(service_id)
            
            if not service or not route:
                continue

            # Get stop times
            stop_times = trip_stop_times.get(trip_id, [])
            if not stop_times:
                continue

            # Calculate start and end times
            first_stop = stop_times[0]
            last_stop = stop_times[-1]
            
            start_time = parse_duration(first_stop["departure_time"])
            end_time = parse_duration(last_stop["arrival_time"])

            # Get calendar
            calendar_data = calendars.get(service_id, {})
            
            # Create or get calendar
            calendar, _ = Calendar.objects.get_or_create(
                source=source,
                start_date=calendar_data.get("start_date", "1970-01-01"),
                defaults={
                    "mon": calendar_data.get("monday", False),
                    "tue": calendar_data.get("tuesday", False),
                    "wed": calendar_data.get("wednesday", False),
                    "thu": calendar_data.get("thursday", False),
                    "fri": calendar_data.get("friday", False),
                    "sat": calendar_data.get("saturday", False),
                    "sun": calendar_data.get("sunday", False),
                    "end_date": calendar_data.get("end_date") or None,
                }
            )

            # Create trip
            trip = Trip(
                route=route,
                calendar=calendar,
                ticket_machine_code=trip_id,
                start=start_time,
                end=end_time,
                inbound=False,  # Could be determined from direction_id if available
            )
            trips_to_create.append(trip)
            trip_map[trip_id] = trip

        # Bulk create trips
        with transaction.atomic():
            Trip.objects.bulk_create(trips_to_create, batch_size=1000)

        return len(trips_to_create)

    def generate_calling_patterns(self, services, trips, trip_stop_times, stations):
        """Generate calling points (stop times) for each timetable entry."""
        # Get trips with their IDs
        trip_ids = list(trips.keys())
        created_trips = {
            trip.ticket_machine_code: trip
            for trip in Trip.objects.filter(ticket_machine_code__in=trip_ids)
        }

        # Create stop times
        stop_times_to_create = []
        
        for trip_id, stop_times in trip_stop_times.items():
            trip = created_trips.get(trip_id)
            if not trip:
                continue

            for stop_time_data in stop_times:
                stop_id = stop_time_data["stop_id"]
                station = stations.get(stop_id)
                
                if not station:
                    continue

                arrival = parse_duration(stop_time_data["arrival_time"])
                departure = parse_duration(stop_time_data["departure_time"])
                
                stop_time = StopTime(
                    trip=trip,
                    stop=station["stop"],
                    arrival=arrival,
                    departure=departure,
                    sequence=stop_time_data["stop_sequence"],
                    pick_up=True,
                    set_down=True,
                )
                stop_times_to_create.append(stop_time)

        # Bulk create stop times using COPY for performance
        with connection.cursor() as cursor:
            with cursor.copy(
                "COPY bustimes_stoptime (trip_id, stop_id, arrival, departure, sequence, pick_up, set_down) FROM STDIN"
            ) as copy:
                for stop_time in stop_times_to_create:
                    copy.write_row((
                        stop_time.trip_id,
                        stop_time.stop_id,
                        int(stop_time.arrival.total_seconds()) if stop_time.arrival else None,
                        int(stop_time.departure.total_seconds()) if stop_time.departure else None,
                        stop_time.sequence,
                        stop_time.pick_up,
                        stop_time.set_down,
                    ))

        return len(stop_times_to_create)
