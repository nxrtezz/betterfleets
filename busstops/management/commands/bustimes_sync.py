from django.core.management import call_command
from django.core.management.base import CommandError

from ._sync_bustimes import BustimesSyncCommand


class Command(BustimesSyncCommand):
    help = "General Bustimes sync command for vehicles, services, stops, journeys, and liveries."

    command_map = {
        "vehicles": "sync_bustimes_vehicles",
        "services": "sync_bustimes_services",
        "stops": "sync_bustimes_stops",
        "journeys": "sync_bustimes_journeys",
        "liveries": "sync_bustimes_liveries",
    }

    def add_arguments(self, parser):
        super().add_arguments(parser)
        for name in self.command_map:
            parser.add_argument(
                f"--{name}",
                action="store_true",
                help=f"Sync {name} from the Bustimes API.",
            )
        parser.add_argument(
            "--operator",
            help="Operator NOC/code filter for vehicle sync requests.",
        )

    def handle(self, *args, **options):
        selected = [name for name in self.command_map if options.get(name)]
        if not selected:
            raise CommandError(
                "Choose at least one sync target, for example `--vehicles`."
            )

        shared_options = {
            "base_url": options.get("base_url"),
            "limit": options.get("limit"),
            "max_items": options.get("max_items"),
            "dry_run": options.get("dry_run"),
            "force": options.get("force"),
            "progress": options.get("progress"),
            "no_progress": options.get("no_progress"),
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

        if len(selected) > 1 and options.get("operator"):
            raise CommandError("`--operator` can only be used with `--vehicles`.")

        for name in selected:
            command_options = dict(shared_options)
            if name == "vehicles" and options.get("operator"):
                command_options["operator"] = options["operator"]
            call_command(self.command_map[name], **command_options)
