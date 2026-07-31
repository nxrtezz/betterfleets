from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from busstops.models import Operator


class Command(BaseCommand):
    help = "Check DVLA data for operators with check_dvla enabled every 72 hours."

    def handle(self, *args, **options):
        operators = Operator.objects.filter(check_dvla=True)
        checked_count = 0
        skipped_count = 0
        error_count = 0

        for operator in operators:
            # Check if 72 hours have passed since last check
            if operator.dvla_last_checked_at:
                time_since_check = timezone.now() - operator.dvla_last_checked_at
                if time_since_check < timedelta(hours=72):
                    skipped_count += 1
                    self.stdout.write(
                        f"Skipping {operator.noc} - {operator.name}: "
                        f"last checked {time_since_check.total_seconds() / 3600:.1f} hours ago"
                    )
                    continue

            # Run DVLA import for this operator
            try:
                from django.core.management import call_command

                self.stdout.write(f"Checking DVLA for {operator.noc} - {operator.name}...")
                call_command(
                    "import_dvla",
                    operator=operator.noc,
                    apply=True,
                )
                operator.dvla_last_checked_at = timezone.now()
                operator.save(update_fields=["dvla_last_checked_at"])
                checked_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Successfully checked DVLA for {operator.noc}")
                )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"Error checking DVLA for {operator.noc} - {operator.name}: {e}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"DVLA check complete: {checked_count} checked, "
                f"{skipped_count} skipped (within 72 hours), {error_count} errors"
            )
        )
