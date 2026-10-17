from django.core.management.base import BaseCommand
from django.db import transaction

from busstops.models import Operator, OperatorGroup, Organisation


class Command(BaseCommand):
    help = "Create Stagecoach organisation and split operators by garage (one-time setup)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write("Setting up Stagecoach organisation...")

        # Create or get the Stagecoach organisation
        organisation, created = Organisation.objects.get_or_create(
            slug="stagecoach",
            defaults={
                "name": "Stagecoach",
                "url": "https://www.stagecoachbus.com",
                "description": "Stagecoach Group - one of the UK's largest bus operators",
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created organisation: {organisation}"))
        else:
            self.stdout.write(f"Organisation already exists: {organisation}")

        # Find all Stagecoach operators
        stagecoach_operators = Operator.objects.filter(name__icontains="Stagecoach")

        if not stagecoach_operators.exists():
            self.stdout.write(self.style.WARNING("No Stagecoach operators found"))
            return

        self.stdout.write(f"Found {stagecoach_operators.count()} Stagecoach operators")

        # Create or get a Stagecoach operator group
        group, created = OperatorGroup.objects.get_or_create(
            slug="stagecoach",
            defaults={
                "name": "Stagecoach",
                "organisation": organisation,
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created operator group: {group}"))
        else:
            self.stdout.write(f"Operator group already exists: {group}")

        # Assign all Stagecoach operators to the group
        for operator in stagecoach_operators:
            if operator.group != group:
                if dry_run:
                    self.stdout.write(f"[DRY RUN] Would assign {operator} to group {group}")
                else:
                    operator.group = group
                    operator.save(update_fields=["group"])
                    self.stdout.write(self.style.SUCCESS(f"Assigned {operator} to group {group}"))

        self.stdout.write(self.style.SUCCESS("Stagecoach organisation setup complete"))
        self.stdout.write("\nNote: Garage-specific operator splitting should be done manually")
        self.stdout.write("Use the reassign_stagecoach_vehicles command to move vehicles based on tracking")
