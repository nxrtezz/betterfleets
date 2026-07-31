from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from busstops.models import DataChangeLog, DataSource, Service, ServiceCode
from bustimes.models import Route, StopTime, Trip


class Command(BaseCommand):
    help = (
        "Purge all local services/routes/timetable data and optionally reimport BODS/TNDS. "
        "Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete data. Without this flag only counts are shown.",
        )
        parser.add_argument(
            "--yes-delete-services",
            action="store_true",
            help="Required with --apply. Confirms that all Service rows may be deleted.",
        )
        parser.add_argument(
            "--bod-api-key",
            help="BODS API key. If provided with --apply, BODS will be reimported after purge.",
        )
        parser.add_argument(
            "--tnds-username",
            help="TNDS FTP username. If provided with --apply, TNDS will be reimported after purge.",
        )
        parser.add_argument(
            "--tnds-password",
            help="TNDS FTP password. If provided with --apply, TNDS will be reimported after purge.",
        )
        parser.add_argument(
            "--skip-reimport",
            action="store_true",
            help="Only purge/reset; do not call the BODS importer.",
        )
        parser.add_argument(
            "--reset-all-timetable-sources",
            action="store_true",
            help="Clear datetime/sha1 on every timetable DataSource, not just BODS DataSources.",
        )
        parser.add_argument(
            "--skip-source-seed",
            action="store_true",
            help="Pass through to import_timetable_data when reimporting BODS.",
        )
        parser.add_argument(
            "--skip-operator-fix",
            action="store_true",
            help="Pass through to import_timetable_data when reimporting BODS.",
        )

    def get_sources_to_reset(self, reset_all, include_tnds=False):
        sources = DataSource.objects.filter(source__isnull=False)
        if reset_all:
            return sources
        query = Q(url__contains="bus-data.dft.gov.uk")
        if include_tnds:
            query |= Q(url__contains="ftp.tnds.basemap.co.uk")
        return sources.filter(query)

    def write_step(self, message):
        timestamp = timezone.now().strftime("%H:%M:%S")
        self.stdout.write(f"[{timestamp}] {message}")

    def handle(
        self,
        apply=False,
        yes_delete_services=False,
        bod_api_key=None,
        tnds_username=None,
        tnds_password=None,
        skip_reimport=False,
        reset_all_timetable_sources=False,
        skip_source_seed=False,
        skip_operator_fix=False,
        **options,
    ):
        reimport_bods = bool(bod_api_key)
        reimport_tnds = bool(tnds_username or tnds_password)

        if apply and not yes_delete_services:
            raise CommandError(
                "Refusing to purge services without --yes-delete-services."
            )
        if reimport_tnds and not (tnds_username and tnds_password):
            raise CommandError(
                "Pass both --tnds-username and --tnds-password to reimport TNDS."
            )
        if not skip_reimport and apply and not (reimport_bods or reimport_tnds):
            raise CommandError(
                "Pass --bod-api-key and/or TNDS credentials to reimport, or pass --skip-reimport to purge only."
            )

        self.write_step("Counting timetable rows to purge...")
        source_qs = self.get_sources_to_reset(
            reset_all_timetable_sources, include_tnds=reimport_tnds
        )
        counts = {
            "services": Service.objects.count(),
            "service_codes": ServiceCode.objects.count(),
            "routes": Route.objects.count(),
            "trips": Trip.objects.count(),
            "stop_times": StopTime.objects.count(),
            "sources_to_reset": source_qs.count(),
        }

        self.stdout.write(
            "Will purge {services} services, {service_codes} service codes/slugs, "
            "{routes} routes, {trips} trips, {stop_times} stop times, and reset "
            "{sources_to_reset} data sources.".format(
                **counts
            )
        )

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    "Dry run only. Re-run with --apply --yes-delete-services to delete."
                )
            )
            return

        with transaction.atomic():
            self.write_step(
                "Deleting stop times with direct SQL. "
                "This bypasses Django's slow collector but still preserves vehicle rows."
            )
            stop_time_deleted = StopTime.objects.all()._raw_delete(StopTime.objects.db)

            self.write_step("Deleting trips...")
            trip_deleted = Trip.objects.all()._raw_delete(Trip.objects.db)

            self.write_step("Deleting routes...")
            route_deleted = Route.objects.all()._raw_delete(Route.objects.db)

            self.write_step("Deleting services and dependent route slugs/codes...")
            service_deleted = Service.objects.all()._raw_delete(Service.objects.db)

            self.write_step("Resetting timetable source fingerprints...")
            reset_count = source_qs.update(
                datetime=None,
                sha1=None,
                last_modified=None,
                etag="",
            )

            self.write_step("Recording purge in DataChangeLog...")
            DataChangeLog.objects.create(
                source="purge_services_and_reimport",
                target_model="busstops.service",
                target_pk="",
                target_repr="all services/routes/timetable data",
                operation="delete",
                changes={
                    "services": {"from": counts["services"], "to": 0},
                    "service_codes": {"from": counts["service_codes"], "to": 0},
                    "routes": {"from": counts["routes"], "to": 0},
                    "trips": {"from": counts["trips"], "to": 0},
                    "stop_times": {"from": counts["stop_times"], "to": 0},
                    "sources_reset": {"from": counts["sources_to_reset"], "to": reset_count},
                },
                payload={
                    "reset_all_timetable_sources": reset_all_timetable_sources,
                    "skip_reimport": skip_reimport,
                },
                status=DataChangeLog.STATUS_APPLIED,
                applied_at=timezone.now(),
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Purged timetable tables with direct SQL deletes; "
                f"deleted {service_deleted} services, {counts['service_codes']} service codes/slugs, "
                f"{route_deleted} routes, {trip_deleted} trips, {stop_time_deleted} stop times; "
                f"reset {reset_count} data sources."
            )
        )

        if skip_reimport:
            return

        importer_options = {}
        if skip_source_seed:
            importer_options["skip_source_seed"] = True
        if skip_operator_fix:
            importer_options["skip_operator_fix"] = True
        if reimport_bods:
            self.stdout.write(self.style.SUCCESS("Starting full BODS reimport."))
            call_command(
                "import_timetable_data",
                "bod",
                bod_api_key,
                **importer_options,
            )
        if reimport_tnds:
            self.stdout.write(self.style.SUCCESS("Starting full TNDS reimport."))
            call_command("import_tnds", tnds_username, tnds_password)
