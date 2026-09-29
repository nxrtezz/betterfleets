from django.core.management.base import BaseCommand
from django.db.models import Q
from busstops.models import Operator
from vehicles.models import Vehicle
from vehicles.utils import merge_vehicles, is_stagecoach_operator, get_stagecoach_operators


class Command(BaseCommand):
    help = (
        "Merge duplicate vehicles that have the same code but different registration status. "
        "For non-Stagecoach operators, searches within the same operator/group. "
        "For Stagecoach operators, searches across all Stagecoach operators. "
        "Preserves codes during merging to prevent creating more duplicates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be merged without actually merging",
        )
        parser.add_argument(
            "--operator",
            help="Only process a specific operator (by NOC)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Process at most this many operators",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        specific_operator = options.get("operator")
        limit = options.get("limit")

        # Get operators to process
        if specific_operator:
            operators = Operator.objects.filter(noc=specific_operator)
        else:
            operators = Operator.objects.all()

        if limit:
            operators = operators[:limit]

        total_merged = 0
        total_operators_processed = 0

        for operator in operators:
            self.stdout.write(f"\nProcessing operator: {operator.name} ({operator.noc})")
            
            # Find vehicles with code but no reg for this operator
            vehicles_without_reg = Vehicle.objects.filter(
                operator=operator,
                code__isnull=False
            ).filter(reg='').exclude(code='')

            if not vehicles_without_reg.exists():
                self.stdout.write(f"  No vehicles without reg found")
                continue

            self.stdout.write(f"  Found {vehicles_without_reg.count()} vehicles without reg")

            merged_count = 0
            
            for vehicle in vehicles_without_reg:
                code = vehicle.code
                
                # Determine search scope based on whether this is a Stagecoach operator
                if is_stagecoach_operator(operator):
                    # Search across all Stagecoach operators
                    stagecoach_operators = get_stagecoach_operators()
                    matching_vehicles = Vehicle.objects.filter(
                        code__iexact=code,
                        operator__in=stagecoach_operators
                    ).exclude(reg='').exclude(id=vehicle.id)
                else:
                    # Search within same operator (and group if applicable)
                    operator_query = Q(operator=operator)
                    if operator.group_id:
                        operator_query |= Q(operator__group_id=operator.group_id)
                    matching_vehicles = Vehicle.objects.filter(
                        code__iexact=code
                    ).filter(operator_query).exclude(reg='').exclude(id=vehicle.id)

                if not matching_vehicles.exists():
                    continue

                # Get the best match (prefer one with most complete data)
                matching_vehicles = list(matching_vehicles)
                matching_vehicles.sort(
                    key=lambda v: (
                        bool(v.reg),
                        bool(v.vehicle_type),
                        bool(v.fleet_number),
                    ),
                    reverse=True
                )
                
                target_vehicle = matching_vehicles[0]
                
                self.stdout.write(
                    f"  Merging {vehicle} (id: {vehicle.id}) into {target_vehicle} (id: {target_vehicle.id})"
                )
                
                if not dry_run:
                    try:
                        merge_vehicles(vehicle, target_vehicle)
                        merged_count += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"    Error merging: {e}")
                        )
                else:
                    merged_count += 1

            if merged_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f"  Merged {merged_count} vehicles for {operator.name}")
                )
                total_merged += merged_count
            
            total_operators_processed += 1

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Processed {total_operators_processed} operator(s)")
        self.stdout.write(f"Total vehicles merged: {total_merged}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run - no vehicles were actually merged"))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Successfully merged {total_merged} vehicle(s)")
            )