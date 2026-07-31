"""
Import services from multiple sources (TNDS, Passenger, BODS) filtered by NOC.

Usage:
    python manage.py import_services_by_noc <NOC> [--sources SOURCES] [--tnds-username USERNAME] [--tnds-password PASSWORD] [--bods-api-key API_KEY]

Examples:
    python manage.py import_services_by_noc MET --sources passenger,bods
    python manage.py import_services_by_noc Stagecoach --sources tnds,passenger,bods --tnds-username user --tnds-password pass --bods-api-key 1234567890abcdef1234567890abcdef12345678

Environment variables (fallback):
    TNDS_USERNAME, TNDS_PASSWORD, BODS_API_KEY
"""

import logging
import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command

from busstops.models import Operator

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import services from multiple sources filtered by NOC"

    def add_arguments(self, parser):
        parser.add_argument("noc", type=str, help="National Operator Code to filter by")
        parser.add_argument(
            "--sources",
            type=str,
            default="passenger,bods",
            help="Comma-separated list of sources to import from: tnds,passenger,bods (default: passenger,bods)",
        )
        parser.add_argument(
            "--tnds-username",
            type=str,
            default=None,
            help="TNDS FTP username (falls back to TNDS_USERNAME env var if using tnds source)",
        )
        parser.add_argument(
            "--tnds-password",
            type=str,
            default=None,
            help="TNDS FTP password (falls back to TNDS_PASSWORD env var if using tnds source)",
        )
        parser.add_argument(
            "--bods-api-key",
            type=str,
            default=None,
            help="BODS API key (falls back to BODS_API_KEY env var if using bods source)",
        )

    def handle(self, *args, **options):
        noc = options["noc"].upper()
        sources = [s.strip().lower() for s in options["sources"].split(",")]
        valid_sources = {"tnds", "passenger", "bods"}

        # Validate sources
        invalid_sources = set(sources) - valid_sources
        if invalid_sources:
            raise CommandError(
                f"Invalid sources: {', '.join(invalid_sources)}. Valid sources are: {', '.join(valid_sources)}"
            )

        # Validate NOC exists
        operator = Operator.objects.filter(noc__iexact=noc).first()
        if not operator:
            self.stdout.write(
                self.style.WARNING(
                    f"Operator with NOC '{noc}' not found in database. "
                    "The import will proceed but may not match any services."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Found operator: {operator.name} ({operator.noc})")
            )

        self.stdout.write(f"Importing services for NOC: {noc}")
        self.stdout.write(f"Sources: {', '.join(sources)}")

        # Import from each source
        for source in sources:
            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"Importing from {source.upper()}")
            self.stdout.write(f"{'='*60}")

            try:
                if source == "tnds":
                    self.import_tnds(noc, options)
                elif source == "passenger":
                    self.import_passenger(noc)
                elif source == "bods":
                    self.import_bods(noc, options)
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Failed to import from {source}: {e}")
                )
                logger.exception(f"Failed to import from {source}")

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("Import completed"))
        self.stdout.write(f"{'='*60}")

    def import_tnds(self, noc, options):
        """Import from TNDS (requires FTP credentials)"""
        username = options.get("tnds_username") or getattr(settings, "TNDS_USERNAME", None)
        password = options.get("tnds_password") or getattr(settings, "TNDS_PASSWORD", None)

        if not username or not password:
            raise CommandError(
                "TNDS requires --tnds-username/--tnds-password or TNDS_USERNAME/TNDS_PASSWORD env vars"
            )

        self.stdout.write(
            self.style.WARNING(
                "TNDS downloads all files without NOC filtering. "
                "Services will be imported but may include other operators."
            )
        )

        # Note: TNDS doesn't support NOC filtering at download time
        # It downloads all files and processes them through import_transxchange
        call_command("import_tnds", username, password)

    def import_passenger(self, noc):
        """Import from Passenger data source"""
        # Passenger supports operator filtering by name
        # Try to find the operator name from the NOC
        operator = Operator.objects.filter(noc__iexact=noc).first()
        operator_name = operator.name if operator else noc

        self.stdout.write(f"Importing from Passenger for operator: {operator_name}")
        call_command("import_passenger", operator_name)

    def import_bods(self, noc, options):
        """Import from BODS (Bus Open Data)"""
        api_key = options.get("bods_api_key") or getattr(settings, "BODS_API_KEY", None)

        if not api_key:
            raise CommandError("BODS requires --bods-api-key or BODS_API_KEY env var")

        self.stdout.write(f"Importing from BODS for NOC: {noc}")
        call_command("import_bod_timetables", api_key, noc)
