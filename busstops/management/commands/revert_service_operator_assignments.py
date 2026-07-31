from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction

from busstops.models import Service


class Command(BaseCommand):
    help = "Revert service operator assignments made within a specified time window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--minutes",
            type=int,
            default=5,
            help="Only revert assignments made within the last N minutes (default: 5).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only reports actions.",
        )

    def handle(self, *args, minutes=5, apply=False, **options):
        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: reverting service operator assignments.")
        )

        # Find services that were modified recently
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        services = Service.objects.filter(modified_at__gte=cutoff_time).prefetch_related("operator")

        counters = {"services_cleared": 0, "services_skipped": 0}

        with transaction.atomic():
            for service in services:
                if service.operator.exists():
                    counters["services_cleared"] += 1
                    self.stdout.write(
                        f"{service.id} ({service.line_name or service.service_code}): clearing operators"
                    )
                    if apply:
                        service.operator.clear()
                else:
                    counters["services_skipped"] += 1

            if not apply:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "Processed {services_total} services, cleared {services_cleared}, skipped {services_skipped}.".format(
                    services_total=len(services),
                    services_cleared=counters["services_cleared"],
                    services_skipped=counters["services_skipped"],
                )
            )
        )
