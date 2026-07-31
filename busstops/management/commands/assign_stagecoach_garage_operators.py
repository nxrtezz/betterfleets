from __future__ import annotations

import hashlib
from collections import Counter
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from busstops.models import Operator, OperatorGroup, Organisation, Service
from bustimes.models import Garage
from vehicles.models import Vehicle, VehicleJourney


class Command(BaseCommand):
    help = (
        "Assign Stagecoach vehicles and services to garage-specific operators, "
        "delete the original operator, and create an operator group linked to Stagecoach Bus organisation. "
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
            help="Process at most this many vehicles.",
        )
        parser.add_argument(
            "--operator-name",
            default="Stagecoach",
            help="Only process vehicles whose current operator name contains this text.",
        )
        parser.add_argument(
            "--operator",
            "--noc",
            dest="nocs",
            nargs="+",
            help="Only process vehicles whose current operator NOC is in this list.",
        )
        parser.add_argument(
            "--garage-operator-nocs",
            nargs="+",
            help="Only process vehicles whose garage operator NOC is in this list.",
        )

    def normalise_garage_name(self, garage: Garage) -> str:
        name = str(garage or "").strip()
        return " ".join(name.split())

    def get_stagecoach_organisation(self, counters: Counter, apply: bool) -> Organisation:
        organisation = Organisation.objects.filter(name__iexact="Stagecoach Bus").first()
        if organisation:
            return organisation

        counters["organisations_created"] += 1
        if not apply:
            return Organisation(name="Stagecoach Bus", slug="stagecoach-bus")

        organisation, _ = Organisation.objects.get_or_create(
            slug="stagecoach-bus",
            defaults={"name": "Stagecoach Bus"},
        )
        return organisation

    def get_group_for_operator(
        self,
        operator: Operator,
        stagecoach_org: Organisation,
        counters: Counter,
        apply: bool,
    ) -> OperatorGroup | None:
        if operator.group_id:
            group = operator.group
            if (
                stagecoach_org
                and group.organisation_id != stagecoach_org.pk
                and apply
            ):
                group.organisation = stagecoach_org
                group.save(update_fields=["organisation"])
                counters["groups_linked_to_organisation"] += 1
            return group

        group_name = operator.name.strip()
        if not group_name:
            return None

        group = OperatorGroup.objects.filter(name__iexact=group_name).first()
        if not group:
            counters["groups_created"] += 1
            if apply:
                group = OperatorGroup.objects.create(
                    name=group_name,
                    slug=slugify(group_name)[:48],
                    organisation=stagecoach_org,
                )
            else:
                group = OperatorGroup(name=group_name, slug=slugify(group_name)[:48])
        elif stagecoach_org and group.organisation_id != stagecoach_org.pk and apply:
            group.organisation = stagecoach_org
            group.save(update_fields=["organisation"])
            counters["groups_linked_to_organisation"] += 1

        if apply:
            update_fields = []
            if not operator.group_id:
                operator.group = group
                update_fields.append("group")
            if stagecoach_org and operator.organisation_id != stagecoach_org.pk:
                operator.organisation = stagecoach_org
                update_fields.append("organisation")
            if update_fields:
                operator.save(update_fields=update_fields)
                counters["source_operators_updated"] += 1

        return group

    def build_generated_noc(self, garage_name: str) -> str:
        digest = hashlib.sha1(garage_name.lower().encode("utf-8")).hexdigest()[:8].upper()
        return f"SC{digest}"

    def get_target_operator(
        self,
        garage_name: str,
        source_operator: Operator,
        group: OperatorGroup | None,
        organisation: Organisation,
        counters: Counter,
        apply: bool,
    ) -> Operator:
        target_name = f"Stagecoach {garage_name}"
        external_id = f"stagecoach-garage:{slugify(garage_name)}"
        operator = (
            Operator.objects.filter(name__iexact=target_name).first()
            or Operator.objects.filter(external_id=external_id).first()
        )
        if operator:
            if apply:
                update_fields = []
                if group and operator.group_id != group.pk:
                    operator.group = group
                    update_fields.append("group")
                if organisation and operator.organisation_id != organisation.pk:
                    operator.organisation = organisation
                    update_fields.append("organisation")
                if source_operator.region_id and operator.region_id != source_operator.region_id:
                    operator.region = source_operator.region
                    update_fields.append("region")
                if update_fields:
                    operator.save(update_fields=update_fields)
                    counters["garage_operators_updated"] += 1
            return operator

        counters["garage_operators_created"] += 1
        if not apply:
            return Operator(
                noc=self.build_generated_noc(garage_name),
                name=target_name,
                slug=slugify(target_name)[:50],
                external_id=external_id,
                organisation=organisation,
                group=group,
                region=source_operator.region,
                is_manual=True,
            )

        operator = Operator.objects.create(
            noc=self.build_generated_noc(garage_name),
            name=target_name,
            slug=slugify(target_name)[:50],
            external_id=external_id,
            organisation=organisation,
            group=group,
            region=source_operator.region,
            is_manual=True,
        )
        return operator

    def move_vehicle(self, vehicle: Vehicle, target_operator: Operator, counters: Counter, apply: bool):
        if vehicle.operator_id == target_operator.pk:
            counters["already_assigned"] += 1
            return

        counters["vehicles_reassigned"] += 1
        if apply:
            vehicle.operator = target_operator
            vehicle.save(update_fields=["operator"])

    def move_service(self, service: Service, source_operator: Operator, target_operator: Operator, counters: Counter, apply: bool):
        if not service.operator.filter(pk=source_operator.pk).exists():
            return

        counters["services_moved"] += 1
        if apply:
            service.operator.remove(source_operator)
            service.operator.add(target_operator)

    def get_service_garage_operator(self, service: Service, garage_operators_by_source: dict[Operator, dict[Garage, Operator]], counters: Counter) -> Operator | None:
        """Determine the garage operator for a service based on the vehicles operating that service."""
        # Get vehicles that operate this service via VehicleJourney
        vehicle_journeys = VehicleJourney.objects.filter(
            service=service,
            vehicle__isnull=False,
            vehicle__garage__isnull=False
        ).select_related("vehicle__garage").distinct()
        
        if not vehicle_journeys:
            counters["services_without_vehicle_journeys"] += 1
            return None
        
        # Count vehicles by garage
        garage_counts = Counter()
        for journey in vehicle_journeys:
            if journey.vehicle.garage:
                garage_counts[journey.vehicle.garage] += 1
        
        if not garage_counts:
            counters["services_without_garages"] += 1
            return None
        
        # Find the most common garage
        most_common_garage = garage_counts.most_common(1)[0][0]
        
        # Find the target operator for this garage
        for source_operator, garage_to_operator_map in garage_operators_by_source.items():
            if most_common_garage in garage_to_operator_map:
                return garage_to_operator_map[most_common_garage]
        
        counters["services_without_matching_garage_operator"] += 1
        return None

    def align_garage(self, garage: Garage, target_operator: Operator, counters: Counter, apply: bool):
        if garage.operators.filter(pk=target_operator.pk).exists():
            return

        counters["garages_relinked"] += 1
        if apply:
            garage.operators.add(target_operator)

    def handle(
        self,
        *args,
        apply=False,
        limit=None,
        operator_name="Stagecoach",
        nocs=None,
        garage_operator_nocs=None,
        **options,
    ):
        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: writing Stagecoach garage operator changes.")
        )

        vehicles = Vehicle.objects.select_related(
            "operator",
            "garage",
            "operator__group",
            "operator__organisation",
            "operator__region",
        ).filter(
            operator__isnull=False,
            garage__isnull=False,
            withdrawn=False,
        )
        if nocs:
            vehicles = vehicles.filter(operator__noc__in=nocs)
        else:
            vehicles = vehicles.filter(operator__name__icontains=operator_name)
        if garage_operator_nocs:
            vehicles = vehicles.filter(garage__operator__noc__in=garage_operator_nocs)
        vehicles = vehicles.order_by("id")
        if limit is not None:
            vehicles = vehicles[:limit]

        counters = Counter()
        proposed_creations: dict[str, set[str]] = defaultdict(set)
        source_operators_to_delete = set()
        garage_operators_by_source: dict[Operator, dict[Garage, Operator]] = defaultdict(dict)

        with transaction.atomic():
            for vehicle in vehicles:
                source_operator = vehicle.operator
                garage = vehicle.garage
                garage_name = self.normalise_garage_name(garage)
                if not garage_name:
                    counters["vehicles_without_named_garage"] += 1
                    continue

                stagecoach_org = self.get_stagecoach_organisation(counters, apply)
                group = self.get_group_for_operator(
                    source_operator, stagecoach_org, counters, apply
                )

                if apply and stagecoach_org and source_operator.organisation_id != stagecoach_org.pk:
                    source_operator.organisation = stagecoach_org
                    source_operator.save(update_fields=["organisation"])
                    counters["source_operators_updated"] += 1

                target_operator = self.get_target_operator(
                    garage_name,
                    source_operator,
                    group,
                    stagecoach_org,
                    counters,
                    apply,
                )
                if not target_operator.pk:
                    group_name = group.name if group else "Ungrouped"
                    proposed_creations[group_name].add(target_operator.name)
                self.align_garage(garage, target_operator, counters, apply)
                self.move_vehicle(vehicle, target_operator, counters, apply)
                garage_operators_by_source[source_operator][garage] = target_operator
                source_operators_to_delete.add(source_operator)
                counters["vehicles_seen"] += 1

                self.stdout.write(
                    f"{vehicle.pk}: {source_operator.name} -> {target_operator.name} ({garage_name})"
                )

            # Move services from source operators to garage operators based on vehicle garages
            for source_operator in garage_operators_by_source:
                services = Service.objects.filter(operator=source_operator).prefetch_related("operator")
                for service in services:
                    # Determine the garage operator for this service based on its vehicles
                    target_operator = self.get_service_garage_operator(service, garage_operators_by_source, counters)
                    if target_operator:
                        self.move_service(service, source_operator, target_operator, counters, apply)

            # Delete source operators and create operator groups
            for source_operator in source_operators_to_delete:
                garage_to_operator_map = garage_operators_by_source[source_operator]
                garage_operators = set(garage_to_operator_map.values())
                if apply and garage_operators:
                    # Create operator group with source operator's name
                    group_name = source_operator.name.strip()
                    group, created = OperatorGroup.objects.get_or_create(
                        name=group_name,
                        defaults={
                            "slug": slugify(group_name)[:48],
                            "organisation": stagecoach_org,
                        }
                    )
                    if created:
                        counters["groups_created"] += 1
                    else:
                        # Update existing group to link to Stagecoach Bus organisation
                        if group.organisation_id != stagecoach_org.pk:
                            group.organisation = stagecoach_org
                            group.save(update_fields=["organisation"])
                            counters["groups_linked_to_organisation"] += 1

                    # Add all garage operators to this group
                    for garage_operator in garage_operators:
                        if garage_operator.group_id != group.pk:
                            garage_operator.group = group
                            garage_operator.save(update_fields=["group"])
                            counters["garage_operators_updated"] += 1

                    # Delete the source operator
                    source_operator.delete()
                    counters["source_operators_deleted"] += 1

            if not apply:
                transaction.set_rollback(True)

        if proposed_creations:
            heading = (
                "Operators created in this run:"
                if apply
                else "Operators that would be created:"
            )
            self.stdout.write(heading)
            for group_name in sorted(proposed_creations, key=str.casefold):
                self.stdout.write(f"  {group_name}")
                for operator_name in sorted(proposed_creations[group_name], key=str.casefold):
                    self.stdout.write(f"    - {operator_name}")

        self.stdout.write(
            self.style.SUCCESS(
                "Processed {vehicles_seen} vehicles, reassigned {vehicles_reassigned}, already assigned {already_assigned}, "
                "moved {services_moved} services, "
                "services without vehicle journeys {services_without_vehicle_journeys}, "
                "services without garages {services_without_garages}, "
                "services without matching garage operator {services_without_matching_garage_operator}, "
                "created organisations {organisations_created}, groups {groups_created}, garage operators {garage_operators_created}, "
                "updated source operators {source_operators_updated}, updated garage operators {garage_operators_updated}, "
                "relinked garages {garages_relinked}, deleted source operators {source_operators_deleted}.".format(
                    vehicles_seen=counters["vehicles_seen"],
                    vehicles_reassigned=counters["vehicles_reassigned"],
                    already_assigned=counters["already_assigned"],
                    services_moved=counters["services_moved"],
                    services_without_vehicle_journeys=counters.get("services_without_vehicle_journeys", 0),
                    services_without_garages=counters.get("services_without_garages", 0),
                    services_without_matching_garage_operator=counters.get("services_without_matching_garage_operator", 0),
                    organisations_created=counters["organisations_created"],
                    groups_created=counters["groups_created"],
                    garage_operators_created=counters["garage_operators_created"],
                    source_operators_updated=counters["source_operators_updated"],
                    garage_operators_updated=counters["garage_operators_updated"],
                    garages_relinked=counters["garages_relinked"],
                    source_operators_deleted=counters["source_operators_deleted"],
                )
            )
        )
