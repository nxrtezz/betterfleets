from django.core.management.base import BaseCommand
from django.db.models import Q
from busstops.models import Service, StopUsage, Operator, Manufacturer, DataSource


class Command(BaseCommand):
    help = 'Convert service descriptions to format: {first inbound} - {last inbound}'

    def add_arguments(self, parser):
        parser.add_argument(
            '--operator',
            type=str,
            help='Filter by operator NOC (e.g., YCST)',
        )
        parser.add_argument(
            '--division',
            type=str,
            help='Filter by manufacturer/division slug (e.g., alexander-dennis)',
        )
        parser.add_argument(
            '--source',
            type=str,
            help='Filter by data source name (e.g., NCSD)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be changed without actually changing',
        )
        parser.add_argument(
            '--commit',
            action='store_true',
            help='Actually apply the changes (required for non-dry-run)',
        )

    def handle(self, *args, **options):
        operator_noc = options.get('operator')
        division_slug = options.get('division')
        source_name = options.get('source')
        dry_run = options.get('dry_run', False)
        commit = options.get('commit', False)

        # Build queryset with filters
        queryset = Service.objects.all()

        if operator_noc:
            queryset = queryset.filter(operator__noc=operator_noc)
            self.stdout.write(f"Filtering by operator: {operator_noc}")

        if division_slug:
            queryset = queryset.filter(operator__organisation__manufacturer__slug=division_slug)
            self.stdout.write(f"Filtering by division: {division_slug}")

        if source_name:
            queryset = queryset.filter(source__name=source_name)
            self.stdout.write(f"Filtering by source: {source_name}")

        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} services to process")

        if total_count == 0:
            self.stdout.write(self.style.WARNING("No services found matching criteria"))
            return

        if not dry_run and not commit:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - use --commit to apply changes"))
            dry_run = True

        updated_count = 0
        skipped_count = 0

        for service in queryset.iterator():
            # Get inbound stops ordered by sequence
            inbound_stops = StopUsage.objects.filter(
                service=service,
                inbound=True
            ).order_by('order')

            if inbound_stops.count() < 2:
                skipped_count += 1
                if dry_run:
                    self.stdout.write(f"Skipping {service.service_code or service.id}: insufficient inbound stops")
                continue

            first_stop = inbound_stops.first()
            last_stop = inbound_stops.last()

            if not first_stop or not last_stop:
                skipped_count += 1
                continue

            first_stop_name = first_stop.stop.get_qualified_name(short=True)
            last_stop_name = last_stop.stop.get_qualified_name(short=True)

            new_description = f"{first_stop_name} - {last_stop_name}"

            if service.description == new_description:
                skipped_count += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"Would update {service.service_code or service.id}: "
                    f"'{service.description}' -> '{new_description}'"
                )
            else:
                old_description = service.description
                service.description = new_description
                service.save(update_fields=['description'])
                self.stdout.write(
                    f"Updated {service.service_code or service.id}: "
                    f"'{old_description}' -> '{new_description}'"
                )
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nSummary: {'Would update' if dry_run else 'Updated'} {updated_count} services, "
            f"skipped {skipped_count}"
        ))
