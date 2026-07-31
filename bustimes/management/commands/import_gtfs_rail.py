import logging
from pathlib import Path

import gtfs_kit
import pandas as pd
from django.contrib.gis.geos import GEOSGeometry
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count
from django.utils.dateparse import parse_duration
from django.utils import timezone

from busstops.models import DataSource, Operator, Region, Service, StopCode, StopPoint

from ...gtfs_utils import do_route_links, get_calendars
from ...models import Route, Trip

logger = logging.getLogger(__name__)


def truncate(value, length):
    return str(value or "")[:length]


def infer_stop_type(row) -> str:
    location_type = getattr(row, "location_type", None)
    platform_code = str(getattr(row, "platform_code", "") or "").strip()

    if platform_code:
        return "RPL"
    if location_type == 1:
        return "RSE"
    if location_type in (0, None):
        return "RPL"
    return "RLY"


class Command(BaseCommand):
    help = "Import GTFS rail timetables into the shared timetable models."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to a GTFS zip file.")
        parser.add_argument(
            "--source-name",
            default="National Rail GTFS",
            help="Data source name to create or update.",
        )
        parser.add_argument(
            "--source-url",
            default="",
            help="Optional URL to store against the data source.",
        )
        parser.add_argument(
            "--operator-name",
            default="National Rail",
            help="Operator name to attach imported services to.",
        )
        parser.add_argument(
            "--operator-code",
            default="RAIL",
            help="Operator code/NOC-like identifier to create or re-use.",
        )
        parser.add_argument(
            "--region",
            help="Optional region id to assign to services and operator.",
        )

    def get_source(self, options):
        source, _ = DataSource.objects.get_or_create(name=options["source_name"])
        update_fields = []
        if options["source_url"] and source.url != options["source_url"]:
            source.url = options["source_url"]
            update_fields.append("url")
        if update_fields:
            source.save(update_fields=update_fields)
        return source

    def get_operator(self, source, options):
        code = options["operator_code"]
        defaults = {"name": options["operator_name"], "source": source}
        operator, created = Operator.objects.get_or_create(noc=code, defaults=defaults)
        update_fields = []
        if not created and operator.name != options["operator_name"]:
            operator.name = options["operator_name"]
            update_fields.append("name")
        if not operator.source_id:
            operator.source = source
            update_fields.append("source")
        if region_id := options.get("region"):
            region = Region.objects.get(id=region_id)
            if operator.region_id != region.id:
                operator.region = region
                update_fields.append("region")
        if update_fields:
            operator.save(update_fields=update_fields)
        return operator

    def build_stop(self, row, source):
        stop = StopPoint(
            atco_code=f"rail-{row.stop_id}",
            common_name=truncate(row.stop_name, 48) or row.stop_id,
            short_common_name=truncate(getattr(row, "tts_stop_name", ""), 48),
            indicator=truncate(getattr(row, "platform_code", ""), 48),
            stop_type=infer_stop_type(row),
            active=True,
            source=source,
        )
        if pd.notna(row.stop_lon) and pd.notna(row.stop_lat):
            stop.latlong = GEOSGeometry(f"POINT({row.stop_lon} {row.stop_lat})")
        return stop

    def get_service_name(self, row):
        line_name = str(getattr(row, "route_short_name", "") or "").strip()
        description = str(getattr(row, "route_long_name", "") or "").strip()
        if not line_name:
            line_name = description or str(row.route_id)
        return truncate(line_name, 64), truncate(description, 255)

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"GTFS archive not found: {path}")

        source = self.get_source(options)
        operator = self.get_operator(source, options)
        feed = gtfs_kit.read_feed(path, dist_units="km")

        if (
            feed.stops is None
            or feed.routes is None
            or feed.trips is None
            or feed.stop_times is None
        ):
            raise CommandError(
                "GTFS feed is missing one of stops.txt, routes.txt, trips.txt, or stop_times.txt"
            )

        calendars = get_calendars(feed, source)

        existing_routes = {route.code: route for route in source.route_set.all()}
        existing_services = {
            service.service_code: service for service in source.service_set.filter(current=True)
        }

        feed_stops = {row.stop_id: row for row in feed.stops.itertuples()}
        stop_ids = [f"rail-{row.stop_id}" for row in feed.stops.itertuples()]
        existing_stops = StopPoint.objects.in_bulk(stop_ids)
        new_stops = []
        updated_stops = []
        stop_id_map = {}

        for row in feed.stops.itertuples():
            atco_code = f"rail-{row.stop_id}"
            stop_id_map[row.stop_id] = atco_code
            stop = self.build_stop(row, source)
            if atco_code in existing_stops:
                existing = existing_stops[atco_code]
                changed = False
                for field in ("common_name", "short_common_name", "indicator", "stop_type", "source_id", "active"):
                    value = getattr(stop, field)
                    if getattr(existing, field) != value:
                        setattr(existing, field, value)
                        changed = True
                if existing.latlong != stop.latlong:
                    existing.latlong = stop.latlong
                    changed = True
                if changed:
                    updated_stops.append(existing)
            else:
                new_stops.append(stop)

        StopPoint.objects.bulk_create(new_stops, batch_size=1000)
        if updated_stops:
            StopPoint.objects.bulk_update(
                updated_stops,
                ["common_name", "short_common_name", "indicator", "stop_type", "source", "active", "latlong"],
                batch_size=1000,
            )

        rail_stops = StopPoint.objects.in_bulk(stop_ids)

        existing_stop_codes = {
            (stop_code.code, stop_code.source_id): stop_code
            for stop_code in StopCode.objects.filter(source=source)
        }
        stop_codes_to_create = []
        for row in feed.stops.itertuples():
            stop = rail_stops[f"rail-{row.stop_id}"]
            for code in {str(row.stop_id).strip(), str(getattr(row, "stop_code", "") or "").strip()}:
                if not code:
                    continue
                key = (code, source.id)
                if key not in existing_stop_codes:
                    stop_codes_to_create.append(StopCode(stop=stop, source=source, code=code))
                    existing_stop_codes[key] = True
        StopCode.objects.bulk_create(stop_codes_to_create, ignore_conflicts=True, batch_size=1000)

        geometries = {}
        try:
            for row in feed.get_routes(as_gdf=True).itertuples():
                if row.geometry:
                    geometries[row.route_id] = row.geometry.wkt
        except (AttributeError, ValueError):
            logger.info("GTFS rail feed has no route geometries")

        routes = {}
        for row in feed.routes.itertuples():
            line_name, description = self.get_service_name(row)
            service = existing_services.get(str(row.route_id))
            if not service:
                service = Service(service_code=str(row.route_id))
            service.line_name = line_name
            service.description = description
            service.mode = "rail"
            service.current = True
            service.source = source
            service.geometry = geometries.get(row.route_id)
            if region_id := options.get("region"):
                service.region_id = region_id
            service.save()
            service.operator.set([operator])

            route = existing_routes.get(str(row.route_id))
            if not route:
                route = Route(code=str(row.route_id), source=source)
            route.service = service
            route.line_name = line_name
            route.description = description
            route.service_code = str(row.route_id)
            route.line_id = str(getattr(row, "route_id", "") or "")
            route.public_use = True
            route.save()
            routes[row.route_id] = route
            existing_services[str(row.route_id)] = service

        existing_trips = {
            trip.ticket_machine_code: trip
            for trip in Trip.objects.filter(route__source=source).exclude(ticket_machine_code__isnull=True)
        }
        trips = {}
        for row in feed.trips.itertuples():
            route = routes[row.route_id]
            trip_code = str(row.trip_id)
            trip = Trip(
                route=route,
                calendar=calendars[row.service_id],
                inbound=int(getattr(row, "direction_id", 0) or 0) == 1,
                headsign=truncate(getattr(row, "trip_headsign", ""), 255) or None,
                ticket_machine_code=trip_code,
                vehicle_journey_code=truncate(getattr(row, "trip_short_name", ""), 100) or trip_code,
                journey_pattern=truncate(getattr(row, "shape_id", ""), 100) or None,
                block=truncate(getattr(row, "block_id", ""), 100),
                operator=operator,
            )
            if trip_code in existing_trips:
                trip.id = existing_trips[trip_code].id
            trips[trip_code] = trip

        trip_stop_rows = {}
        for row in feed.stop_times.sort_values(["trip_id", "stop_sequence"]).itertuples():
            trip_stop_rows.setdefault(row.trip_id, []).append(row)

        for trip_id, rows in trip_stop_rows.items():
            trip = trips.get(str(trip_id))
            if not trip:
                continue
            first = rows[0]
            last = rows[-1]
            trip.start = parse_duration(first.departure_time)
            trip.end = parse_duration(last.arrival_time)
            trip.destination_id = stop_id_map[last.stop_id]

        with transaction.atomic():
            Trip.objects.bulk_create([trip for trip in trips.values() if not trip.id], batch_size=1000)
            existing_trip_rows = [trip for trip in trips.values() if trip.id]
            if existing_trip_rows:
                Trip.objects.bulk_update(
                    existing_trip_rows,
                    [
                        "route",
                        "calendar",
                        "inbound",
                        "headsign",
                        "ticket_machine_code",
                        "vehicle_journey_code",
                        "journey_pattern",
                        "block",
                        "start",
                        "end",
                        "destination",
                        "operator",
                    ],
                    batch_size=1000,
                )
                from ...models import StopTime

                StopTime.objects.filter(
                    trip_id__in=[trip.id for trip in existing_trip_rows]
                ).delete()

            with (
                connection.cursor() as cursor,
                cursor.copy(
                    "COPY bustimes_stoptime (stop_id, arrival, departure, sequence, trip_id, timing_status, pick_up, set_down, stop_code) FROM STDIN"
                ) as copy,
            ):
                for trip_id, rows in trip_stop_rows.items():
                    trip = trips.get(str(trip_id))
                    if not trip or not trip.pk:
                        continue
                    for row in rows:
                        arrival = int(parse_duration(row.arrival_time).total_seconds())
                        departure = int(parse_duration(row.departure_time).total_seconds())
                        stop_code = str(getattr(feed_stops[row.stop_id], "stop_code", "") or row.stop_id)
                        pickup_type = getattr(row, "pickup_type", 0)
                        drop_off_type = getattr(row, "drop_off_type", 0)
                        copy.write_row(
                            (
                                stop_id_map[row.stop_id],
                                arrival if arrival != departure else None,
                                departure,
                                row.stop_sequence,
                                trip.pk,
                                "PTP" if getattr(row, "timepoint", 1) == 1 else "OTH",
                                pickup_type != 1,
                                drop_off_type != 1,
                                stop_code,
                            )
                        )

            current_services = source.service_set.filter(current=True)
            imported_route_ids = [route.id for route in routes.values()]
            source.route_set.exclude(id__in=imported_route_ids).update(service=None)
            current_services.exclude(route__id__in=imported_route_ids).update(current=False)

            for service in Service.objects.filter(id__in=[route.service_id for route in routes.values()]):
                service.do_stop_usages()
                if not service.region_id:
                    region = (
                        Region.objects.filter(adminarea__stoppoint__service=service)
                        .annotate(Count("adminarea__stoppoint__service"))
                        .order_by("-adminarea__stoppoint__service__count")
                        .first()
                    )
                    if region:
                        service.region = region
                        service.save(update_fields=["region"])
                service.update_search_vector()

            source.datetime = timezone.now()
            source.save(update_fields=["datetime"])

        do_route_links(feed, source, routes, feed_stops, stop_id_map, mode="rail")
