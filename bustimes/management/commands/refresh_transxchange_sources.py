from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from busstops.models import DataChangeLog, DataSource, Service
from bustimes.download_utils import download
from bustimes.management.commands.import_bod_timetables import get_version, handle_file
from bustimes.management.commands.import_transxchange import Command as TransXChangeCommand
from bustimes.models import Route, StopTime, TimetableDataSource, Trip
from bustimes.utils import get_sha1


PASSENGER_URL_PREFIX = "https://data.discoverpassenger.com/operator"
PASSENGER_URL_SUFFIX = "/open-data"
TICKETER_URL_PREFIX = "https://opendata.ticketer.com"


class Command(BaseCommand):
    help = (
        "Refresh one or more direct TransXChange timetable sources: delete the "
        "existing imported rows for each selected source, download the current "
        "archive, and import it again."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "sources",
            nargs="*",
            help="TimetableDataSource name, URL, or numeric id.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Refresh every active direct TransXChange timetable source.",
        )
        parser.add_argument(
            "--keep-archives",
            action="store_true",
            help="Do not delete downloaded archives after import.",
        )

    def get_base_queryset(self):
        return (
            TimetableDataSource.objects.filter(active=True)
            .exclude(url="")
            .exclude(url__startswith=PASSENGER_URL_PREFIX)
            .exclude(url__endswith=PASSENGER_URL_SUFFIX)
            .exclude(url__startswith=TICKETER_URL_PREFIX)
            .order_by("id")
        )

    def get_sources(self, selectors, include_all):
        queryset = self.get_base_queryset()
        if include_all:
            if selectors:
                raise CommandError("Pass source selectors or --all, not both.")
            return list(queryset)

        if not selectors:
            raise CommandError("Pass at least one source selector or use --all.")

        sources = []
        seen = set()
        for selector in selectors:
            match = (
                queryset.filter(Q(url=selector) | Q(name=selector)).first()
                or (queryset.filter(id=int(selector)).first() if selector.isdigit() else None)
            )
            if not match:
                raise CommandError(f"Could not find active direct TransXChange source {selector!r}.")
            if match.id not in seen:
                seen.add(match.id)
                sources.append(match)
        return sources

    def archive_path_for(self, timetable_source):
        archive_dir = settings.DATA_DIR / "transxchange"
        archive_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(timetable_source.url).suffix.lower()
        if suffix not in {".zip", ".xml"}:
            suffix = ".zip"
        return archive_dir / f"{timetable_source.id}{suffix}"

    def purge_existing_rows(self, timetable_source):
        linked_sources = list(DataSource.objects.filter(source=timetable_source))
        source_ids = [source.id for source in linked_sources]

        if not source_ids:
            return {
                "sources": 0,
                "services": 0,
                "routes": 0,
                "trips": 0,
                "stop_times": 0,
                "sources_reset": 0,
            }

        services = Service.objects.filter(source_id__in=source_ids)
        routes = Route.objects.filter(source_id__in=source_ids)
        trips = Trip.objects.filter(route__source_id__in=source_ids)
        stop_times = StopTime.objects.filter(trip__route__source_id__in=source_ids)

        counts = {
            "sources": len(source_ids),
            "services": services.count(),
            "routes": routes.count(),
            "trips": trips.count(),
            "stop_times": stop_times.count(),
        }

        with transaction.atomic():
            stop_time_deleted = stop_times._raw_delete(StopTime.objects.db)
            trip_deleted = trips._raw_delete(Trip.objects.db)
            route_deleted = routes._raw_delete(Route.objects.db)
            service_deleted = services._raw_delete(Service.objects.db)
            reset_count = DataSource.objects.filter(id__in=source_ids).update(
                datetime=None,
                sha1=None,
                last_modified=None,
                etag="",
            )

        counts["services"] = service_deleted
        counts["routes"] = route_deleted
        counts["trips"] = trip_deleted
        counts["stop_times"] = stop_time_deleted
        counts["sources_reset"] = reset_count
        return counts

    def import_source(self, timetable_source, archive_path):
        command = TransXChangeCommand()
        command.set_up()
        command.source, _ = DataSource.objects.get_or_create(
            url=timetable_source.url,
            defaults={"name": timetable_source.name},
        )
        command.source.name = timetable_source.name
        command.source.url = timetable_source.url
        command.source.source = timetable_source
        command.source.datetime = timezone.now()
        command.region_id = timetable_source.region_id
        command.service_ids = set()
        command.route_ids = set()
        command.garages = {}
        command.version = get_version(
            timetable_source,
            command.source,
            name=archive_path.name,
            url=timetable_source.url,
            when=command.source.datetime,
        )

        relative_path = archive_path.relative_to(settings.DATA_DIR)
        handle_file(command, relative_path)

        command.finish_services()
        command.source.sha1 = get_sha1(archive_path)
        command.source.save()

    def log_refresh(self, timetable_source, purge_counts):
        DataChangeLog.objects.create(
            source="refresh_transxchange_sources",
            target_model="bustimes.timetabledatasource",
            target_pk=str(timetable_source.pk),
            target_repr=timetable_source.name,
            operation="import",
            changes={
                "services": {"from": purge_counts["services"], "to": 0},
                "routes": {"from": purge_counts["routes"], "to": 0},
                "trips": {"from": purge_counts["trips"], "to": 0},
                "stop_times": {"from": purge_counts["stop_times"], "to": 0},
                "sources_reset": {
                    "from": purge_counts["sources"],
                    "to": purge_counts["sources_reset"],
                },
            },
            payload={"url": timetable_source.url},
            status=DataChangeLog.STATUS_APPLIED,
            applied_at=timezone.now(),
        )

    def handle(self, *args, **options):
        sources = self.get_sources(options["sources"], options["all"])
        keep_archives = options["keep_archives"]

        for timetable_source in sources:
            self.stdout.write(self.style.SUCCESS(f"Refreshing {timetable_source.name}"))
            purge_counts = self.purge_existing_rows(timetable_source)
            archive_path = self.archive_path_for(timetable_source)

            download(archive_path, timetable_source.url)
            self.import_source(timetable_source, archive_path)
            self.log_refresh(timetable_source, purge_counts)

            if not keep_archives and archive_path.exists():
                archive_path.unlink()

