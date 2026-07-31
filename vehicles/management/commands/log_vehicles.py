import json
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from vehicles.models import Vehicle
from fleet.completion import bulk_log_vehicles_for_user

User = get_user_model()


class Command(BaseCommand):
    help = "Log all vehicles from a JSON file for a given user based on registrations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            required=True,
            help="Username to log vehicles for",
        )
        parser.add_argument(
            "--file",
            required=True,
            help="Path to the JSON file containing passage records",
        )

    def handle(self, *args, **options):
        username = options["user"]
        file_path = options["file"]

        # Get the user
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist.")

        self.stdout.write(f"Processing file for user: {user.username} (ID: {user.id})")

        # Load the JSON file
        try:
            with open(file_path, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            raise CommandError(f"File not found: {file_path}")
        except json.JSONDecodeError as e:
            raise CommandError(f"Invalid JSON file: {e}")

        # Process all records (ignore user ID in JSON)
        self.stdout.write(f"Processing {len(data)} records from JSON file")

        # Extract registrations from assets
        registrations = set()
        for record in data.values():
            assets = record.get("Asset35654a")
            if not assets:
                continue
            for asset in assets:
                reg = asset.get("IdentReg8de79c", "").strip()
                if reg:
                    registrations.add(reg)

        if not registrations:
            self.stdout.write(self.style.WARNING("No registrations found in records"))
            return

        self.stdout.write(f"Found {len(registrations)} unique registrations")

        # Find vehicles by registration
        vehicles_to_log = []
        not_found = []
        for reg in registrations:
            # Try to find vehicle by registration (case-insensitive, spaces removed)
            compact_reg = reg.replace(" ", "").upper()
            vehicles = Vehicle.objects.filter(reg__iexact=compact_reg)
            if vehicles.exists():
                vehicles_to_log.extend(vehicles)
            else:
                not_found.append(reg)

        if not vehicles_to_log:
            self.stdout.write(
                self.style.WARNING("No vehicles found matching the registrations")
            )
            if not_found:
                self.stdout.write(
                    f"Registrations not found: {', '.join(not_found[:10])}"
                    + (f" ... and {len(not_found) - 10} more" if len(not_found) > 10 else "")
                )
            return

        # Remove duplicates
        vehicles_to_log = list(set(vehicles_to_log))
        self.stdout.write(f"Found {len(vehicles_to_log)} vehicles to log")

        if not_found:
            self.stdout.write(
                self.style.WARNING(
                    f"Registrations not found: {len(not_found)} "
                    f"(showing first 10: {', '.join(not_found[:10])})"
                )
            )

        # Log vehicles for user
        created, skipped = bulk_log_vehicles_for_user(user, vehicles_to_log)

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully logged {created} vehicle(s) for {username}. "
                f"Skipped {skipped} already logged vehicle(s)."
            )
        )
