from unittest.mock import patch

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction

from vehicles.models import Livery


class Command(BaseCommand):
    help = "Publish every livery currently applied to a train vehicle."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many train liveries would be published without saving changes.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        liveries = Livery.objects.filter(
            vehicle__vehicle_type__style="train",
            published=False,
        ).distinct()

        count = liveries.count()
        preview = list(liveries.order_by("name", "id").values_list("id", "name")[:25])

        for livery_id, name in preview:
            self.stdout.write(f"publish {livery_id}: {name}")
        if count > len(preview):
            self.stdout.write(f"...and {count - len(preview)} more")

        with patch.object(cache, "set", lambda *args, **kwargs: None), transaction.atomic():
            if not dry_run:
                liveries.update(published=True)
            else:
                transaction.set_rollback(True)

        prefix = "Dry run: " if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"{prefix}published={count}"))
