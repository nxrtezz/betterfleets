from django.core.management.base import BaseCommand
from django.db.models import Q
from busstops.models import Operator
from vehicles.models import Vehicle, VehicleCode
from vehicles.utils import is_stagecoach_operator, get_stagecoach_operators


class Command(BaseCommand):
    help = (
        "Merge vehicles by matching code-only vehicles with vehicles that have the same fleet number. "
        "For non-Stagecoach operators, searches within the same operator/group. "
        "For Stagecoach operators, searches across all Stagecoach operators. "
        "Updates the target vehicle's code to match the source vehicle's code, then deletes the source."
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
        parser.add_argument(
            "--show-table",
            action="store_true",
            help="Show a table of code-only vehicles and potential matches",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        specific_operator = options.get("operator")
        limit = options.get("limit")
        show_table = options.get("show_table")

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

            if show_table:
                self.stdout.write(f"\n  {'ID':<8} {'Code':<20} {'Fleet #':<10} {'Reg':<15}")
                self.stdout.write(f"  {'-'*60}")
                for vehicle in vehicles_without_reg:
                    self.stdout.write(
                        f"  {vehicle.id:<8} {vehicle.code:<20} {str(vehicle.fleet_number or ''):<10} {vehicle.reg:<15}"
                    )

            merged_count = 0
            
            for vehicle in vehicles_without_reg:
                code = vehicle.code
                fleet_number = code if code.isdigit() else None
                
                if not fleet_number:
                    # Try to extract fleet number from code if it's not just digits
                    # e.g., "SK65PWJ_35164" -> extract "35164"
                    if '_' in code:
                        parts = code.split('_')
                        for part in parts:
                            if part.isdigit():
                                fleet_number = part
                                break
                
                if not fleet_number:
                    continue
                
                # Determine search scope based on whether this is a Stagecoach operator
                if is_stagecoach_operator(operator):
                    # Search across all Stagecoach operators
                    stagecoach_operators = get_stagecoach_operators()
                    matching_vehicles = Vehicle.objects.filter(
                        fleet_number=fleet_number,
                        operator__in=stagecoach_operators
                    ).exclude(id=vehicle.id)
                else:
                    # Search within same operator (and group if applicable)
                    operator_query = Q(operator=operator)
                    if operator.group_id:
                        operator_query |= Q(operator__group_id=operator.group_id)
                    matching_vehicles = Vehicle.objects.filter(
                        fleet_number=fleet_number
                    ).filter(operator_query).exclude(id=vehicle.id)

                if not matching_vehicles.exists():
                    continue

                # Get the best match (prefer one with reg and most complete data)
                matching_vehicles = list(matching_vehicles)
                matching_vehicles.sort(
                    key=lambda v: (
                        bool(v.reg),
                        bool(v.vehicle_type),
                    ),
                    reverse=True
                )
                
                target_vehicle = matching_vehicles[0]
                
                self.stdout.write(
                    f"  Found match: {vehicle} (code: {vehicle.code}) -> {target_vehicle} (code: {target_vehicle.code}, fleet_number: {target_vehicle.fleet_number}, reg: {target_vehicle.reg})"
                )
                
                if not dry_run:
                    try:
                        # Check if updating the code would violate the unique constraint
                        conflicting_vehicle = Vehicle.objects.filter(
                            code__iexact=code,
                            operator=target_vehicle.operator
                        ).exclude(id=target_vehicle.id).first()
                        
                        if conflicting_vehicle:
                            # There's already a vehicle with this code for the same operator
                            # We need to delete the conflicting vehicle instead
                            self.stdout.write(
                                f"    Found conflicting vehicle {conflicting_vehicle.id} with code '{code}', deleting it first"
                            )
                            
                            # Move journeys from conflicting vehicle to target
                            from vehicles.models import VehicleJourney
                            VehicleJourney.objects.filter(vehicle=conflicting_vehicle).update(vehicle=target_vehicle)
                            
                            # Move VehicleCode records from conflicting vehicle to target
                            conflicting_codes = VehicleCode.objects.filter(vehicle=conflicting_vehicle)
                            for conflicting_code in conflicting_codes:
                                conflicting_code.vehicle = target_vehicle
                                conflicting_code.save()
                            
                            # Delete the conflicting vehicle
                            conflicting_vehicle.delete()
                        
                        # Now update target vehicle's code to match source vehicle's code
                        old_code = target_vehicle.code
                        target_vehicle.code = code
                        target_vehicle.save(update_fields=['code'])
                        
                        # Move all VehicleCode records from source to target
                        source_codes = VehicleCode.objects.filter(vehicle=vehicle)
                        for source_code in source_codes:
                            source_code.vehicle = target_vehicle
                            source_code.save()
                        
                        # Reassign vehicle journeys from source to target
                        from vehicles.models import VehicleJourney
                        VehicleJourney.objects.filter(vehicle=vehicle).update(vehicle=target_vehicle)
                        
                        # Delete the source vehicle
                        vehicle.delete()
                        
                        self.stdout.write(
                            f"    Updated {target_vehicle.id} code from '{old_code}' to '{code}' and deleted {vehicle.id}"
                        )
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