"""Safely re-import an existing downloaded BODS dataset."""
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from busstops.models import DataSource
from .import_bod_timetables import get_command, handle_file

class Command(BaseCommand):
    help = "Recover missing timetable data from cached provider datasets"
    def add_arguments(self, parser):
        parser.add_argument("--source", type=int, nargs="+", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--force", action="store_true", help="Reparse existing routes to repair old operator mappings")
    def handle(self, *args, **options):
        failures = []
        for source_id in options["source"]:
            path = settings.DATA_DIR / "bod" / str(source_id)
            source = DataSource.objects.filter(pk=source_id).first()
            if source is None or not path.is_file():
                failures.append(source_id)
                self.stderr.write(f"Missing source/cache: {source_id}")
                continue
            self.stdout.write(f"Cached dataset {source_id}: {source.name}", ending="\n")
            if not options["apply"]:
                continue
            try:
                with transaction.atomic():
                    if options["force"]:
                        from bustimes.models import Route
                        Route.objects.filter(source=source).update(file_hash=None)
                    command = get_command()
                    command.source = source
                    command.region_id = source.source.region_id if source.source_id else None
                    command.service_ids = set()
                    command.route_ids = set()
                    command.garages = {}
                    handle_file(command, path)
                    command.mark_old_services_as_not_current()
                    command.finish_services()
                    self.stdout.write(f"RECOVERED {source_id}: {len(command.service_ids)} services")
            except Exception as exc:
                failures.append(source_id)
                self.stderr.write(f"FAILED {source_id}: {type(exc).__name__}: {exc}")
        if failures:
            raise CommandError(f"Cached recovery failed for source IDs: {failures}")
