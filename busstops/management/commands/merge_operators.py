from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from busstops.models import Operator


class Command(BaseCommand):
    help = (
        "Merge one or more source operators into a target operator. "
        "All vehicles, services, and related data will be moved from source operators to the target. "
        "Dry-run by default; pass --apply to write changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "source_operators",
            nargs="+",
            help="NOC(s), slug(s), or name(s) of source operators to merge (space-separated).",
        )
        parser.add_argument(
            "target_operator",
            help="NOC, slug, or name of target operator to merge into.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only reports actions.",
        )

    def resolve_operator(self, value):
        """Resolve an operator by NOC, slug, or name."""
        operator = (
            Operator.objects.filter(noc__iexact=value).first()
            or Operator.objects.filter(slug__iexact=value).first()
            or Operator.objects.filter(name__iexact=value).first()
        )
        if not operator:
            raise CommandError(f"Could not find operator matching {value!r}")
        return operator

    def handle(self, source_operators, target_operator, apply=False, **options):
        # Resolve target operator
        target = self.resolve_operator(target_operator)
        
        # Resolve source operators
        sources = []
        for source_value in source_operators:
            source = self.resolve_operator(source_value)
            if source.noc == target.noc:
                self.stdout.write(
                    self.style.WARNING(f"Skipping {source.noc}: same as target operator")
                )
                continue
            sources.append(source)
        
        if not sources:
            raise CommandError("No valid source operators to merge.")
        
        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: merging operators.")
        )
        
        self.stdout.write(f"Target operator: {target.noc} ({target.name})")
        self.stdout.write(f"Source operators: {', '.join(f'{s.noc} ({s.name})' for s in sources)}")
        
        with transaction.atomic():
            for source in sources:
                self.stdout.write(f"\nProcessing {source.noc} ({source.name}) -> {target.noc} ({target.name})")
                
                # Count objects to be moved
                vehicle_count = source.vehicle_set.count()
                service_count = source.service_set.count()
                depot_count = source.depot_set.count()
                
                self.stdout.write(f"  Vehicles: {vehicle_count}")
                self.stdout.write(f"  Services: {service_count}")
                self.stdout.write(f"  Depots: {depot_count}")
                
                if apply:
                    try:
                        # Move vehicles
                        from vehicles.models import Vehicle, VehicleRevision
                        from fleet.models import PinnedOperator
                        
                        Vehicle.objects.filter(operator=source).update(operator=target)
                        Vehicle.objects.filter(operated_by=source).update(operated_by=target)
                        Vehicle.objects.filter(historical_fleet=source).update(historical_fleet=target)
                        VehicleRevision.objects.filter(from_operator=source).update(from_operator=target)
                        VehicleRevision.objects.filter(to_operator=source).update(to_operator=target)
                        VehicleRevision.objects.filter(from_operated_by=source).update(from_operated_by=target)
                        VehicleRevision.objects.filter(to_operated_by=source).update(to_operated_by=target)
                        PinnedOperator.objects.filter(operator=source).update(operator=target)
                        
                        # Move services
                        source.service_set.all().update(operator=target)
                        
                        # Move depots
                        source.depot_set.all().update(operator=target)
                        
                        # Move operator codes
                        source.operatorcode_set.all().update(operator=target)
                        
                        # Move operator vehicle columns
                        source.operatorvehiclecolumn_set.all().update(operator=target)
                        
                        # Move operator group depots
                        from busstops.models import OperatorGroupDepot
                        OperatorGroupDepot.objects.filter(operator=source).update(operator=target)
                        
                        # Delete source operator
                        source.delete()
                        
                        self.stdout.write(
                            self.style.SUCCESS(f"  Successfully merged {source.noc} into {target.noc}")
                        )
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"  Error merging {source.noc}: {str(e)}")
                        )
                        raise
                else:
                    self.stdout.write(f"  Would merge {source.noc} into {target.noc}")
        
        if not apply:
            transaction.set_rollback(True)
            self.stdout.write(
                self.style.SUCCESS("\nDry run complete. Use --apply to perform the merge.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nSuccessfully merged {len(sources)} operator(s) into {target.noc}")
            )
