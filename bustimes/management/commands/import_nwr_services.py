import gzip
import json
import logging
from pathlib import Path
from collections import defaultdict
from datetime import time, date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_duration

from busstops.models import DataSource, Operator, Region, Service, StopPoint
from bustimes.models import Route, Trip, StopTime, Calendar

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import Network Rail CIF schedule data from /NWR/ folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="/NWR",
            help="Path to NWR folder containing CIF JSON files.",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Import full schedule file (CIF_ALL_FULL_DAILY_*.json.gz).",
        )
        parser.add_argument(
            "--apply-updates",
            action="store_true",
            help="Apply incremental update files (CIF_ALL_UPDATE_DAILY_*.json.gz).",
        )
        parser.add_argument(
            "--purge",
            action="store_true",
            help="Remove previously imported NWR services and rebuild from scratch.",
        )

    def handle(self, *args, **options):
        nwr_path = Path(options["path"])
        if not nwr_path.exists():
            raise CommandError(f"NWR path not found: {nwr_path}")

        if options["purge"]:
            self.purge_existing_data()

        self.stdout.write("Loading NWR schedule files...")

        # Scan folder for CIF files
        cif_files = self.scan_cif_files(nwr_path)
        
        if not cif_files:
            raise CommandError("No CIF files found in NWR path")

        # Select files based on options
        files_to_process = self.select_files(cif_files, options)
        
        self.stdout.write(f"Processing {len(files_to_process)} CIF file(s)...")

        # Phase 1: Load TIPLOC mappings
        self.stdout.write("Resolving stations (TIPLOC → CRS)...")
        tiploc_map = self.build_tiploc_map(files_to_process)
        resolved_count = sum(1 for v in tiploc_map.values() if v["crs"])
        total_count = len(tiploc_map)
        resolution_rate = (resolved_count / total_count * 100) if total_count > 0 else 0
        self.stdout.write(f"Resolved stations: {resolution_rate:.1f}% ({resolved_count}/{total_count})")

        # Phase 2: Process schedules
        self.stdout.write("Parsing CIF schedule feeds...")
        schedules = self.parse_schedules(files_to_process)
        self.stdout.write(f"Schedules found: {len(schedules):,}")

        # Phase 3: Generate services
        self.stdout.write("Generating services...")
        services = self.generate_services(schedules, tiploc_map)
        operator_service_counts = defaultdict(int)
        for service in services.values():
            for operator in service.operator.all():
                operator_service_counts[operator.name] += 1
        
        for operator_name, count in sorted(operator_service_counts.items()):
            self.stdout.write(f"{operator_name}: {count} services")
        
        self.stdout.write(f"Services created: {len(services)}")

        # Phase 4: Generate timetable entries
        self.stdout.write("Generating timetables...")
        timetable_count = self.generate_timetables(services, schedules, tiploc_map)
        self.stdout.write(f"Timetable entries created: {timetable_count:,}")

        # Phase 5: Generate calling points
        self.stdout.write("Generating calling points...")
        calling_points_count = self.generate_calling_points(schedules, tiploc_map)
        self.stdout.write(f"Calling points created: {calling_points_count:,}")

        self.stdout.write(self.style.SUCCESS("Import complete."))

    def purge_existing_data(self):
        """Remove previously imported NWR services and related data."""
        self.stdout.write("Purging existing NWR services...")
        
        # Get the NWR data source
        try:
            source = DataSource.objects.get(name="Network Rail CIF")
        except DataSource.DoesNotExist:
            self.stdout.write("No existing NWR data source found.")
            return

        # Delete related data in order
        with transaction.atomic():
            # Delete stop times for NWR trips
            nwr_trips = Trip.objects.filter(route__source=source)
            StopTime.objects.filter(trip__in=nwr_trips).delete()
            
            # Delete trips
            nwr_trips.delete()
            
            # Delete routes
            Route.objects.filter(source=source).delete()
            
            # Delete services
            Service.objects.filter(source=source).delete()
            
            # Delete the source
            source.delete()

        self.stdout.write("Purge complete.")

    def scan_cif_files(self, nwr_path):
        """Scan NWR folder for CIF JSON files."""
        cif_files = []
        
        for file_path in nwr_path.glob("*.json.gz"):
            if file_path.name.startswith("CIF_ALL_FULL_DAILY"):
                cif_files.append(("full", file_path))
            elif file_path.name.startswith("CIF_ALL_UPDATE_DAILY"):
                cif_files.append(("update", file_path))
        
        return sorted(cif_files, key=lambda x: x[1].name)

    def select_files(self, cif_files, options):
        """Select files to process based on options."""
        if options["full"]:
            # Only process full files
            return [f for f in cif_files if f[0] == "full"]
        elif options["apply_updates"]:
            # Process all files
            return cif_files
        else:
            # Default: process latest full file only
            full_files = [f for f in cif_files if f[0] == "full"]
            if full_files:
                return [full_files[-1]]  # Latest full file
            return []

    def build_tiploc_map(self, files_to_process):
        """Build TIPLOC → CRS mapping from CIF files."""
        tiploc_map = {}
        
        for file_type, file_path in files_to_process:
            self.stdout.write(f"Reading TIPLOCs from {file_path.name}...")
            
            with gzip.open(file_path, 'rt') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if "TiplocV1" in data:
                            tiploc_data = data["TiplocV1"]
                            tiploc_code = tiploc_data.get("tiploc_code")
                            crs_code = tiploc_data.get("crs_code")
                            description = tiploc_data.get("description") or tiploc_data.get("tps_description")
                            
                            if tiploc_code:
                                tiploc_map[tiploc_code] = {
                                    "crs": crs_code,
                                    "description": description,
                                }
                    except json.JSONDecodeError:
                        continue
        
        # Enhance with existing StopPoint CRS codes
        existing_stops = StopPoint.objects.exclude(crs_code__isnull=True).exclude(crs_code="")
        for stop in existing_stops:
            # Could add logic to match by description if needed
            pass
        
        return tiploc_map

    def parse_schedules(self, files_to_process):
        """Parse schedule entries from CIF files."""
        schedules = []
        
        for file_type, file_path in files_to_process:
            self.stdout.write(f"Parsing schedules from {file_path.name}...")
            
            with gzip.open(file_path, 'rt') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        if "JsonScheduleV1" in data:
                            schedules.append(data["JsonScheduleV1"])
                    except json.JSONDecodeError:
                        continue
        
        return schedules

    def resolve_station(self, tiploc_code, tiploc_map):
        """Resolve TIPLOC to StopPoint."""
        if not tiploc_code:
            return None
        
        tiploc_data = tiploc_map.get(tiploc_code)
        if not tiploc_data:
            return None
        
        crs_code = tiploc_data.get("crs")
        if crs_code:
            # Try to find by CRS code
            try:
                return StopPoint.objects.get(crs_code=crs_code)
            except StopPoint.DoesNotExist:
                pass
        
        # Try to find by description
        description = tiploc_data.get("description")
        if description:
            try:
                return StopPoint.objects.filter(common_name__icontains=description[:30]).first()
            except StopPoint.DoesNotExist:
                pass
        
        # Create unresolved station marker
        return None

    def generate_services(self, schedules, tiploc_map):
        """Generate services with deduplication based on (operator, origin_crs, destination_crs)."""
        # Get or create data source
        source, _ = DataSource.objects.get_or_create(
            name="Network Rail CIF",
            defaults={"url": ""}
        )

        # Build service key to track deduplication
        service_keys = {}  # (operator_id, origin_crs, destination_crs) -> service
        services = {}  # service_key -> Service object

        # Process each schedule to generate services
        for schedule in schedules:
            # Extract operator
            atoc_code = schedule.get("atoc_code")
            if not atoc_code:
                continue
            
            # Try to find operator by ATOC code
            operator = Operator.objects.filter(noc__iexact=atoc_code).first()
            if not operator:
                # Create new operator
                operator = Operator.objects.create(
                    noc=atoc_code[:10],
                    name=atoc_code,
                    vehicle_mode="rail",
                )

            # Get schedule locations
            schedule_segment = schedule.get("schedule_segment")
            if not schedule_segment:
                continue
            
            schedule_locations = schedule_segment.get("schedule_location", [])
            if not schedule_locations:
                continue

            # Get origin and destination
            origin_location = schedule_locations[0]
            destination_location = schedule_locations[-1]
            
            origin_tiploc = origin_location.get("tiploc_code")
            destination_tiploc = destination_location.get("tiploc_code")
            
            if not origin_tiploc or not destination_tiploc:
                continue

            # Resolve stations
            origin_station = self.resolve_station(origin_tiploc, tiploc_map)
            destination_station = self.resolve_station(destination_tiploc, tiploc_map)
            
            # Get CRS codes
            origin_crs = tiploc_map.get(origin_tiploc, {}).get("crs") or origin_tiploc
            destination_crs = tiploc_map.get(destination_tiploc, {}).get("crs") or destination_tiploc
            
            # Get names
            origin_name = tiploc_map.get(origin_tiploc, {}).get("description") or origin_tiploc
            destination_name = tiploc_map.get(destination_tiploc, {}).get("description") or destination_tiploc

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
            else:
                service = service_keys[service_key]

            # Store schedule with service reference
            schedule["_service_key"] = service_key
            schedule["_service"] = service_keys[service_key]

        return service_keys

    def generate_timetables(self, services, schedules, tiploc_map):
        """Generate timetable entries (trips) linked to services."""
        # Get or create data source
        source, _ = DataSource.objects.get_or_create(
            name="Network Rail CIF",
            defaults={"url": ""}
        )

        # Create routes for each service
        routes = {}
        for service_key, service in services.items():
            route, _ = Route.objects.get_or_create(
                source=source,
                code=service_key[1] + "-" + service_key[2],  # origin-destination
                defaults={
                    "service": service,
                    "line_name": service.line_name,
                    "description": service.description,
                }
            )
            routes[service_key] = route

        # Create trips
        trips_to_create = []
        trip_map = {}  # train_uid -> Trip object

        for schedule in schedules:
            service_key = schedule.get("_service_key")
            if not service_key:
                continue
            
            service = services.get(service_key)
            route = routes.get(service_key)
            
            if not service or not route:
                continue

            # Extract schedule details
            train_uid = schedule.get("CIF_train_uid")
            headcode = schedule.get("CIF_headcode")
            atoc_code = schedule.get("atoc_code")
            
            # Get dates
            schedule_start_date = schedule.get("schedule_start_date")
            schedule_end_date = schedule.get("schedule_end_date")
            
            if not schedule_start_date:
                continue
            
            # Parse dates
            try:
                start_date = date.fromisoformat(schedule_start_date)
                end_date = date.fromisoformat(schedule_end_date) if schedule_end_date else None
            except ValueError:
                continue

            # Get operating days from CIF bitmask
            days_run = schedule.get("schedule_days_runs", "0000000")
            days_map = {
                "mon": days_run[0] == "1",
                "tue": days_run[1] == "1",
                "wed": days_run[2] == "1",
                "thu": days_run[3] == "1",
                "fri": days_run[4] == "1",
                "sat": days_run[5] == "1",
                "sun": days_run[6] == "1",
            }

            # Get origin and destination times
            schedule_segment = schedule.get("schedule_segment")
            if not schedule_segment:
                continue
            
            schedule_locations = schedule_segment.get("schedule_location", [])
            if not schedule_locations:
                continue
            
            origin_location = schedule_locations[0]
            destination_location = schedule_locations[-1]
            
            # Parse times (CIF format: HHMM or HH:MM)
            departure_str = origin_location.get("public_departure")
            arrival_str = destination_location.get("public_arrival")
            
            departure_time = self.parse_cif_time(departure_str)
            arrival_time = self.parse_cif_time(arrival_str)
            
            if not departure_time or not arrival_time:
                continue

            # Get destination station
            destination_tiploc = destination_location.get("tiploc_code")
            destination_station = self.resolve_station(destination_tiploc, tiploc_map)

            # Create calendar
            calendar, _ = Calendar.objects.get_or_create(
                source=source,
                start_date=start_date,
                defaults={
                    "mon": days_map["mon"],
                    "tue": days_map["tue"],
                    "wed": days_map["wed"],
                    "thu": days_map["thu"],
                    "fri": days_map["fri"],
                    "sat": days_map["sat"],
                    "sun": days_map["sun"],
                    "end_date": end_date,
                }
            )

            # Create trip
            trip = Trip(
                route=route,
                calendar=calendar,
                ticket_machine_code=train_uid,
                vehicle_journey_code=headcode or train_uid,
                start=timedelta(hours=departure_time.hour, minutes=departure_time.minute),
                end=timedelta(hours=arrival_time.hour, minutes=arrival_time.minute),
                destination=destination_station,
                inbound=False,
                operator=service.operator.first(),
            )
            trips_to_create.append(trip)
            trip_map[train_uid] = trip

        # Bulk create trips
        with transaction.atomic():
            Trip.objects.bulk_create(trips_to_create, batch_size=1000)

        return len(trips_to_create)

    def generate_calling_points(self, schedules, tiploc_map):
        """Generate calling points (stop times) for each trip."""
        # Get trips with their IDs
        train_uids = [s.get("CIF_train_uid") for s in schedules if s.get("CIF_train_uid")]
        created_trips = {
            trip.ticket_machine_code: trip
            for trip in Trip.objects.filter(ticket_machine_code__in=train_uids)
        }

        # Create stop times
        stop_times_to_create = []
        
        for schedule in schedules:
            train_uid = schedule.get("CIF_train_uid")
            trip = created_trips.get(train_uid)
            if not trip:
                continue
            
            schedule_segment = schedule.get("schedule_segment")
            if not schedule_segment:
                continue
            
            schedule_locations = schedule_segment.get("schedule_location", [])
            
            for idx, location in enumerate(schedule_locations):
                tiploc_code = location.get("tiploc_code")
                if not tiploc_code:
                    continue
                
                # Resolve station
                station = self.resolve_station(tiploc_code, tiploc_map)
                if not station:
                    # Skip unresolved stations for now
                    continue
                
                # Parse times
                arrival_str = location.get("public_arrival")
                departure_str = location.get("public_departure")
                
                arrival_time = self.parse_cif_time(arrival_str)
                departure_time = self.parse_cif_time(departure_str)
                
                # Create stop time
                arrival_seconds = None
                departure_seconds = None
                
                if arrival_time:
                    arrival_seconds = arrival_time.hour * 3600 + arrival_time.minute * 60
                if departure_time:
                    departure_seconds = departure_time.hour * 3600 + departure_time.minute * 60
                
                stop_time = StopTime(
                    trip=trip,
                    stop=station,
                    arrival=arrival_seconds,
                    departure=departure_seconds,
                    sequence=idx,
                    pick_up=True,
                    set_down=True,
                )
                stop_times_to_create.append(stop_time)

        # Bulk create stop times using COPY for performance
        with connection.cursor() as cursor:
            with cursor.copy(
                "COPY bustimes_stoptime (trip_id, stop_id, arrival, departure, sequence, pick_up, set_down) FROM STDIN"
            ) as copy:
                for st in stop_times_to_create:
                    copy.write_row((
                        st.trip_id,
                        st.stop_id,
                        st.arrival,
                        st.departure,
                        st.sequence,
                        st.pick_up,
                        st.set_down,
                    ))

        return len(stop_times_to_create)

    def parse_cif_time(self, time_str):
        """Parse CIF time format (HHMM or HH:MM) to time object."""
        if not time_str:
            return None
        
        # Remove any non-digit characters except colon
        time_str = time_str.strip().replace(":", "")
        
        if len(time_str) == 4 and time_str.isdigit():
            try:
                hour = int(time_str[:2])
                minute = int(time_str[2:4])
                return time(hour=hour, minute=minute)
            except ValueError:
                return None
        
        return None
