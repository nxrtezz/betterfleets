from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from busstops.models import DataChangeLog, DataSource, Service
from bustimes.management.commands.import_transxchange import TNDS_SOURCE_NAMES
from bustimes.models import Route, StopTime, Trip


class Command(BaseCommand):
    help = (
        "Replace TNDS timetable data only: remove existing TNDS rows and archives, "
        "then run a fresh TNDS import."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", type=str)
        parser.add_argument("password", type=str)
        parser.add_argument(
            "--keep-archives",
            action="store_true",
            help="Do not delete downloaded TNDS ZIP archives before reimporting.",
        )

    def get_tnds_sources(self):
        return DataSource.objects.filter(
            Q(url__contains="ftp.tnds.basemap.co.uk") | Q(name__in=TNDS_SOURCE_NAMES)
        )

    def get_archive_paths(self, sources):
        names = {
            Path(source.url).name
            for source in sources
            if source.url and source.url.startswith("ftp://") and source.url.endswith(".zip")
        }
        names.update(f"{name}.zip" for name in TNDS_SOURCE_NAMES if name != "L")
        names.add("IOM.zip")
        return [settings.TNDS_DIR / name for name in sorted(names)]

    def handle(self, username, password, keep_archives=False, **options):
        if not username or not password:
            raise CommandError("Both TNDS username and password are required.")

        sources = list(self.get_tnds_sources())
        source_ids = [source.id for source in sources]

        services = Service.objects.filter(source_id__in=source_ids)
        routes = Route.objects.filter(
            Q(source_id__in=source_ids) | Q(service__source_id__in=source_ids)
        )
        trips = Trip.objects.filter(route__in=routes)
        stop_times = StopTime.objects.filter(trip__in=trips)

        counts = {
            "sources": len(source_ids),
            "services": services.count(),
            "routes": routes.count(),
            "trips": trips.count(),
            "stop_times": stop_times.count(),
        }

        archive_paths = self.get_archive_paths(sources)
        deleted_archives = 0

        with transaction.atomic():
            stop_time_deleted = stop_times._raw_delete(StopTime.objects.db)
            trip_deleted = trips._raw_delete(Trip.objects.db)
            route_deleted = routes._raw_delete(Route.objects.db)
            service_deleted = services._raw_delete(Service.objects.db)
            reset_count = self.get_tnds_sources().update(
                datetime=None,
                sha1=None,
                last_modified=None,
                etag="",
            )

            DataChangeLog.objects.create(
                source="refresh_tnds_data",
                target_model="busstops.service",
                target_pk="",
                target_repr="TNDS services/routes/timetable data",
                operation="delete",
                changes={
                    "services": {"from": counts["services"], "to": 0},
                    "routes": {"from": counts["routes"], "to": 0},
                    "trips": {"from": counts["trips"], "to": 0},
                    "stop_times": {"from": counts["stop_times"], "to": 0},
                    "sources_reset": {"from": counts["sources"], "to": reset_count},
                },
                payload={"keep_archives": keep_archives},
                status=DataChangeLog.STATUS_APPLIED,
                applied_at=timezone.now(),
            )

        if not keep_archives:
            for path in archive_paths:
                if path.exists():
                    path.unlink()
                    deleted_archives += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Removed existing TNDS data; "
                f"deleted {service_deleted} services, {route_deleted} routes, "
                f"{trip_deleted} trips, {stop_time_deleted} stop times; "
                f"reset {reset_count} data sources and deleted {deleted_archives} archives."
            )
        )

        self.stdout.write(self.style.SUCCESS("Starting fresh TNDS import."))
        call_command("import_tnds", username, password)
