from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Run a safer Bustimes reimport sequence: sync liveries, purge imported vehicles, "
        "reimport fleet data, then repair unresolved liveries"
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--operator", help="Filter by operator noc or slug")
        parser.add_argument("--livery", help="Filter vehicles by Bustimes livery id/external_id")
        parser.add_argument("--since", help="Incremental watermark where supported by API")
        parser.add_argument("--limit", type=int, help="Maximum items per endpoint request")
        parser.add_argument("--skip-liveries", action="store_true")
        parser.add_argument("--skip-purge", action="store_true")
        parser.add_argument("--skip-repair", action="store_true")
        parser.add_argument("--skip-operators", action="store_true")

    def handle(self, *args, **options):
        shared = {
            "dry_run": options["dry_run"],
            "since": options.get("since"),
            "limit": options.get("limit"),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }
        if options.get("operator"):
            shared["operator"] = options["operator"]
        if options.get("livery"):
            shared["livery"] = options["livery"]

        self.stdout.write(self.style.MIGRATE_HEADING("Bustimes reimport plan"))
        self.stdout.write("1. Sync liveries")
        self.stdout.write("2. Purge Bustimes-imported vehicles")
        self.stdout.write("3. Reimport fleet data")
        self.stdout.write("4. Repair unresolved liveries")

        if not options.get("skip_liveries"):
            self.stdout.write(self.style.HTTP_INFO("Syncing Bustimes liveries"))
            livery_options = {
                "dry_run": options["dry_run"],
                "since": options.get("since"),
                "limit": options.get("limit"),
                "stdout": self.stdout,
                "stderr": self.stderr,
            }
            if options.get("livery"):
                livery_options["livery"] = options["livery"]
            call_command("sync_bustimes_liveries", **livery_options)

        if not options.get("skip_purge"):
            self.stdout.write(self.style.HTTP_INFO("Purging Bustimes-imported vehicles"))
            purge_options = {
                "dry_run": options["dry_run"],
                "stdout": self.stdout,
                "stderr": self.stderr,
            }
            if options.get("operator"):
                purge_options["operator"] = options["operator"]
            call_command("purge_bustimes_fleet", **purge_options)

        self.stdout.write(self.style.HTTP_INFO("Reimporting Bustimes fleet"))
        sync_options = {
            **shared,
            "skip_operators": options.get("skip_operators", False),
        }
        call_command("sync_bustimes_fleet", **sync_options)

        if not options.get("skip_repair"):
            self.stdout.write(self.style.HTTP_INFO("Repairing unresolved liveries"))
            repair_options = {
                "dry_run": options["dry_run"],
                "since": options.get("since"),
                "limit": options.get("limit"),
                "stdout": self.stdout,
                "stderr": self.stderr,
            }
            if options.get("operator"):
                repair_options["operator"] = options["operator"]
            call_command("repair_vehicle_liveries", **repair_options)
