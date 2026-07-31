from pathlib import Path

import requests
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from busstops.models import DataChangeLog, Operator
from bustimes.models import TimetableDataSource


BODS_API_KEY_LENGTH = 40
BODS_SPECIAL_IMPORTERS = {"stagecoach", "ticketer"}


def is_noc(value):
    return bool(value) and len(value) <= 10 and value.upper() == value and value.isalnum()


class Command(BaseCommand):
    help = "Import timetable data with a small source-aware wrapper."

    def add_arguments(self, parser):
        parser.add_argument(
            "source",
            choices=("bod", "transxchange", "gtfs"),
            help="Timetable source type.",
        )
        parser.add_argument(
            "inputs",
            nargs="*",
            help=(
                "BODS API key, TransXChange archive path, or optional GTFS "
                "collection names. GTFS imports all configured collections when omitted."
            ),
        )
        parser.add_argument(
            "--operator",
            help="Operator NOC, slug, or name. Used where the underlying importer supports narrowing.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Pass through force import where supported.",
        )
        parser.add_argument(
            "--skip-source-seed",
            action="store_true",
            help="Do not discover and create missing BODS timetable source rows before a global BODS import.",
        )
        parser.add_argument(
            "--all-local-operators",
            action="store_true",
            help="Seed BODS source rows for every local operator instead of only operators found in published BODS datasets.",
        )
        parser.add_argument(
            "--keep-unpublished-sources",
            action="store_true",
            help="Keep active local NOC BODS sources even when that NOC is not currently published in BODS.",
        )
        parser.add_argument(
            "--skip-operator-fix",
            action="store_true",
            help="Do not repair service/operator mappings after a BODS import.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate inputs and show what would run without changing data.",
        )

    def log_import(self, source, inputs, operator=None):
        DataChangeLog.objects.create(
            source="import_timetable_data",
            target_model="bustimes.timetabledatasource",
            target_pk="",
            target_repr=source,
            operation="import",
            changes={
                "source": {"from": None, "to": source},
                "input_count": {"from": None, "to": len(inputs)},
                "operator": {"from": None, "to": operator.noc if operator else ""},
            },
            payload={"source": source, "input_count": len(inputs)},
            status=DataChangeLog.STATUS_APPLIED,
            applied_at=timezone.now(),
        )

    def resolve_operator(self, value):
        if not value:
            return None
        operator = (
            Operator.objects.filter(noc__iexact=value).first()
            or Operator.objects.filter(slug__iexact=value).first()
            or Operator.objects.filter(name__iexact=value).first()
        )
        if not operator:
            raise CommandError(f"Could not find operator matching {value!r}")
        return operator

    def ensure_bod_source(self, operator):
        source, created = TimetableDataSource.objects.get_or_create(
            name=operator.noc,
            defaults={
                "search": operator.noc,
                "region": operator.region,
            },
        )
        update_fields = []
        if not source.search and not source.url:
            source.search = operator.noc
            update_fields.append("search")
        if not source.region_id and operator.region_id:
            source.region = operator.region
            update_fields.append("region")
        if update_fields:
            source.save(update_fields=update_fields)
        source.operators.add(operator)
        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created BODS timetable source {source.name!r} for {operator.noc}."
                )
            )
        return source

    def get_published_bods_nocs(self, api_key):
        nocs = set()
        url = "https://data.bus-data.dft.gov.uk/api/v1/dataset/"
        params = {
            "api_key": api_key,
            "status": "published",
            "limit": 100,
        }
        session = requests.Session()
        while url:
            response = session.get(url, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("results", []):
                nocs.update(noc for noc in item.get("noc", []) if noc)
            url = payload.get("next")
            params = None
        return nocs

    def deactivate_unpublished_bod_sources(self, published_nocs):
        source_ids = []
        sources = TimetableDataSource.objects.filter(
            url="",
            active=True,
        ).exclude(search="")
        for source in sources.only("id", "search"):
            if is_noc(source.search) and source.search not in published_nocs:
                source_ids.append(source.id)
        if not source_ids:
            return 0
        return TimetableDataSource.objects.filter(id__in=source_ids).update(active=False)

    def ensure_bod_sources(
        self,
        api_key,
        all_local_operators=False,
        keep_unpublished_sources=False,
    ):
        created = 0
        linked = 0
        activated = 0
        deactivated = 0
        operators = Operator.objects.exclude(noc="").exclude(preserved=True).order_by(
            "noc"
        )
        if not all_local_operators:
            published_nocs = self.get_published_bods_nocs(api_key)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Found {len(published_nocs)} NOCs in published BODS datasets."
                )
            )
            if not keep_unpublished_sources:
                deactivated = self.deactivate_unpublished_bod_sources(published_nocs)
            operators = operators.filter(noc__in=published_nocs)

        for operator in operators:
            source = (
                TimetableDataSource.objects.filter(url="")
                .filter(Q(name__iexact=operator.noc) | Q(search__iexact=operator.noc))
                .first()
            )
            if not source:
                source = TimetableDataSource.objects.create(
                    name=operator.noc,
                    search=operator.noc,
                    region=operator.region,
                )
                created += 1
            else:
                update_fields = []
                if not source.search:
                    source.search = operator.noc
                    update_fields.append("search")
                if not source.region_id and operator.region_id:
                    source.region = operator.region
                    update_fields.append("region")
                if not source.active:
                    source.active = True
                    update_fields.append("active")
                    activated += 1
                if update_fields:
                    source.save(update_fields=update_fields)

            if not source.operators.filter(noc=operator.noc).exists():
                source.operators.add(operator)
                linked += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"BODS timetable sources ready: {created} created, {linked} linked, {activated} reactivated, {deactivated} unpublished deactivated."
            )
        )

    def get_bod_args(self, inputs, operator, *, dry_run=False):
        if not inputs:
            raise CommandError("BODS import expects a 40-character API key.")

        importer = inputs[0].lower()
        if importer in BODS_SPECIAL_IMPORTERS:
            if len(inputs) != 1:
                raise CommandError(
                    f"BODS {importer!r} import expects no extra positional arguments."
                )
            return [importer, operator.noc] if operator else [importer]

        api_key = inputs[0]
        if len(inputs) > 1:
            joined = "".join(inputs)
            if len(joined) == BODS_API_KEY_LENGTH:
                api_key = joined
                self.stdout.write(
                    self.style.WARNING(
                        "Joined split BODS API key positional arguments into one key."
                    )
                )
            else:
                raise CommandError(
                    "BODS import expects a single 40-character API key. "
                    f"Got {len(inputs)} values which join to {len(joined)} characters."
                )

        if len(api_key) != BODS_API_KEY_LENGTH:
            raise CommandError(
                "BODS API key must be exactly "
                f"{BODS_API_KEY_LENGTH} characters; got {len(api_key)}."
            )

        args = [api_key]
        if operator:
            if dry_run:
                args.append(operator.noc)
            else:
                source = self.ensure_bod_source(operator)
                args.append(source.name)
        return args

    def handle(
        self,
        source,
        inputs,
        operator=None,
        force=False,
        skip_source_seed=False,
        skip_operator_fix=False,
        all_local_operators=False,
        keep_unpublished_sources=False,
        dry_run=False,
        **options,
    ):
        resolved_operator = self.resolve_operator(operator)

        if source == "bod":
            args = self.get_bod_args(inputs, resolved_operator, dry_run=dry_run)
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        "Dry run only. Would import BODS timetable data and run operator repair."
                    )
                )
                return
            if not resolved_operator and not skip_source_seed:
                self.ensure_bod_sources(
                    args[0],
                    all_local_operators=all_local_operators,
                    keep_unpublished_sources=keep_unpublished_sources,
                )
            call_command("import_bod_timetables", *args)
            if not skip_operator_fix:
                fix_options = {"apply": True}
                if resolved_operator:
                    fix_options["operator"] = resolved_operator.noc
                call_command("fix_service_operators", **fix_options)
            self.log_import(source, inputs, resolved_operator)
            return

        if source == "transxchange":
            if not inputs:
                raise CommandError("TransXChange import expects an archive path.")
            archive = Path(inputs[0])
            files = inputs[1:]
            if not archive.exists():
                raise CommandError(f"Archive not found: {archive}")
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"Dry run only. Would import TransXChange archive {archive}."
                    )
                )
                return
            if force:
                self.stdout.write(
                    self.style.WARNING(
                        "TransXChange import does not support --force; importing normally."
                    )
                )
            call_command("import_transxchange", str(archive), *files)
            if resolved_operator:
                self.stdout.write(
                    self.style.WARNING(
                        "TransXChange operator mapping comes from the file operator codes; "
                        f"resolved {resolved_operator.noc} for validation only."
                    )
                )
            self.log_import(source, inputs, resolved_operator)
            return

        if source == "gtfs":
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        "Dry run only. Would import GTFS timetable data."
                    )
                )
                return
            call_command("import_gtfs", *inputs, force=force)
            if resolved_operator:
                self.stdout.write(
                    self.style.WARNING(
                        "GTFS operator mapping comes from agency.txt; "
                        f"resolved {resolved_operator.noc} for validation only."
                    )
                )
            self.log_import(source, inputs, resolved_operator)
