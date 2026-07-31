from collections import Counter
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from busstops.models import Operator, OperatorGroup, Service
from bustimes.models import Garage
from vehicles.models import Vehicle, VehicleJourney


def extract_keywords(text: str) -> list[str]:
    """Extract potential location keywords from a service description."""
    if not text:
        return []
    
    # Split by common delimiters and clean up
    keywords = []
    for delimiter in ["-", " ", "/", "_"]:
        text = text.replace(delimiter, " ")
    
    for word in text.split():
        # Skip very short words or numbers
        if len(word) < 3 or word.isdigit():
            continue
        keywords.append(word.lower())
    
    return keywords


class Command(BaseCommand):
    help = (
        "Reassign services without operators to garage operators based on vehicle garages. "
        "Dry-run by default; pass --apply to write changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only reports actions.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Process at most this many services.",
        )
        parser.add_argument(
            "--operator",
            "--noc",
            help="Assign all services to this operator NOC (fallback when no vehicle journeys exist).",
        )

    def find_operators_by_keywords(self, description: str, line_name: str) -> list[Operator]:
        """Find Stagecoach South operators whose names match keywords in the service description or line name."""
        keywords = extract_keywords(description) + extract_keywords(line_name)
        if not keywords:
            return []

        # Get the Stagecoach South operator group
        stagecoach_south_group = OperatorGroup.objects.filter(name__iexact="Stagecoach South").first()
        if not stagecoach_south_group:
            return []

        # Search for Stagecoach South operators containing any of the keywords
        matched_operators = set()
        for keyword in keywords:
            operators = Operator.objects.filter(
                Q(name__icontains=keyword) & 
                Q(name__icontains="Stagecoach") & 
                Q(group=stagecoach_south_group)
            )
            for op in operators:
                matched_operators.add(op)

        return list(matched_operators)

    def handle(self, *args, apply=False, limit=None, operator=None, **options):
        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: writing service operator changes.")
        )

        # Resolve fallback operator if provided
        fallback_operator = None
        if operator:
            fallback_operator = Operator.objects.filter(noc__iexact=operator).first()
            if not fallback_operator:
                self.stdout.write(self.style.ERROR(f"Operator {operator} not found."))
                return

        # Find services with no operator
        services = Service.objects.filter(operator__isnull=True).order_by("id")
        if limit is not None:
            services = services[:limit]

        counters = Counter()
        results = []

        with transaction.atomic():
            for service in services:
                # Get vehicles that operate this service via VehicleJourney
                vehicle_journeys = VehicleJourney.objects.filter(
                    service=service,
                    vehicle__isnull=False,
                    vehicle__garage__isnull=False,
                    vehicle__operator__isnull=False,
                ).select_related("vehicle__garage", "vehicle__operator").distinct()

                if not vehicle_journeys:
                    # Try to match operators by keywords in description
                    matched_operators = self.find_operators_by_keywords(service.description, service.line_name)
                    if matched_operators:
                        counters["services_assigned_by_keywords"] += 1
                        operator_names = ", ".join(op.name for op in matched_operators)
                        self.stdout.write(
                            f"{service.id} ({service.line_name or service.service_code}): {operator_names} (keyword match)"
                        )
                        if apply:
                            for op in matched_operators:
                                service.operator.add(op)
                    elif fallback_operator:
                        counters["services_assigned_to_fallback"] += 1
                        self.stdout.write(
                            f"{service.id} ({service.line_name or service.service_code}): {fallback_operator.name} (fallback)"
                        )
                        if apply:
                            service.operator.add(fallback_operator)
                    else:
                        counters["services_without_vehicle_journeys"] += 1
                    continue

                # Count vehicles by garage
                garage_counts = Counter()
                garage_to_operator = {}
                for journey in vehicle_journeys:
                    if journey.vehicle.garage and journey.vehicle.operator:
                        garage_counts[journey.vehicle.garage] += 1
                        garage_to_operator[journey.vehicle.garage] = journey.vehicle.operator

                if not garage_counts:
                    # Try to match operators by keywords in description
                    matched_operators = self.find_operators_by_keywords(service.description, service.line_name)
                    if matched_operators:
                        counters["services_assigned_by_keywords"] += 1
                        operator_names = ", ".join(op.name for op in matched_operators)
                        self.stdout.write(
                            f"{service.id} ({service.line_name or service.service_code}): {operator_names} (keyword match - no garage)"
                        )
                        if apply:
                            for op in matched_operators:
                                service.operator.add(op)
                    elif fallback_operator:
                        counters["services_assigned_to_fallback"] += 1
                        self.stdout.write(
                            f"{service.id} ({service.line_name or service.service_code}): {fallback_operator.name} (fallback - no garage)"
                        )
                        if apply:
                            service.operator.add(fallback_operator)
                    else:
                        counters["services_without_garages"] += 1
                    continue

                # Find the most common garage
                most_common_garage = garage_counts.most_common(1)[0][0]
                target_operator = garage_to_operator.get(most_common_garage)

                if not target_operator:
                    # Try to match operators by keywords in description
                    matched_operators = self.find_operators_by_keywords(service.description, service.line_name)
                    if matched_operators:
                        counters["services_assigned_by_keywords"] += 1
                        operator_names = ", ".join(op.name for op in matched_operators)
                        self.stdout.write(
                            f"{service.id} ({service.line_name or service.service_code}): {operator_names} (keyword match - no operator)"
                        )
                        if apply:
                            for op in matched_operators:
                                service.operator.add(op)
                    elif fallback_operator:
                        counters["services_assigned_to_fallback"] += 1
                        self.stdout.write(
                            f"{service.id} ({service.line_name or service.service_code}): {fallback_operator.name} (fallback - no operator)"
                        )
                        if apply:
                            service.operator.add(fallback_operator)
                    else:
                        counters["services_without_operator"] += 1
                    continue

                # Check if service already has this operator
                if service.operator.filter(pk=target_operator.pk).exists():
                    counters["services_already_assigned"] += 1
                    continue

                counters["services_reassigned"] += 1
                results.append(
                    {
                        "service": service,
                        "target_operator": target_operator,
                        "garage": most_common_garage,
                    }
                )
                self.stdout.write(
                    f"{service.id} ({service.line_name or service.service_code}): {target_operator.name} ({most_common_garage})"
                )

                if apply:
                    service.operator.add(target_operator)

            if not apply:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "Processed {services_total} services, reassigned {services_reassigned}, "
                "already assigned {services_already_assigned}, "
                "assigned by keywords {services_assigned_by_keywords}, "
                "assigned to fallback {services_assigned_to_fallback}, "
                "without vehicle journeys {services_without_vehicle_journeys}, "
                "without garages {services_without_garages}, "
                "without operator {services_without_operator}.".format(
                    services_total=len(services),
                    services_reassigned=counters["services_reassigned"],
                    services_already_assigned=counters["services_already_assigned"],
                    services_assigned_by_keywords=counters["services_assigned_by_keywords"],
                    services_assigned_to_fallback=counters["services_assigned_to_fallback"],
                    services_without_vehicle_journeys=counters["services_without_vehicle_journeys"],
                    services_without_garages=counters["services_without_garages"],
                    services_without_operator=counters["services_without_operator"],
                )
            )
        )
