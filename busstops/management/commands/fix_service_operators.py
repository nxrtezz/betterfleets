from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q

from busstops.models import Operator, Service
from bustimes.models import Route, TimetableDataSource, Trip


class Command(BaseCommand):
    help = (
        "Repair service/operator mappings from imported timetable data sources. "
        "Dry-run by default; pass --apply to write changes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            help="Limit to one operator NOC, slug, or name.",
        )
        parser.add_argument(
            "--source",
            action="append",
            default=[],
            help=(
                "Limit to timetable source id, name, or search value. "
                "Can be passed more than once."
            ),
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Only add operators to services that currently have none.",
        )
        parser.add_argument(
            "--set",
            action="store_true",
            dest="replace",
            help=(
                "Replace each service's operator set with the timetable source "
                "operators. By default the command only adds missing links."
            ),
        )
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

    def resolve_operator(self, value):
        if not value:
            return None
        operator = (
            Operator.objects.filter(noc__iexact=value).first()
            or Operator.objects.filter(slug__iexact=value).first()
            or Operator.objects.filter(name__iexact=value).first()
        )
        if not operator:
            raise CommandError(f"Could not find operator matching {value!r}")
        return operator

    def get_sources(self, operator, source_values):
        sources = TimetableDataSource.objects.filter(active=True).prefetch_related(
            "operators"
        )
        if operator:
            sources = sources.filter(operators=operator)
        if source_values:
            query = Q()
            for value in source_values:
                if value.isdigit():
                    query |= Q(pk=int(value))
                query |= Q(name__iexact=value) | Q(search__iexact=value)
            sources = sources.filter(query)
        return sources.distinct().order_by("name", "id")

    def get_service_ids_for_source(self, source, only_missing):
        routes = Route.objects.filter(source__source=source, service__isnull=False)
        services = Service.objects.filter(Exists(routes.filter(service=OuterRef("pk"))))
        if only_missing:
            services = services.annotate(operator_count=Count("operator")).filter(
                operator_count=0
            )
        return services.order_by("id").values_list("id", flat=True).distinct()

    def describe_service(self, service):
        operators = ", ".join(
            service.operator.order_by("noc").values_list("noc", flat=True)
        )
        label = (
            f"{service.id} {service.line_name or ''} {service.description or ''}".strip()
        )
        return label, operators

    def handle(
        self,
        operator=None,
        source=None,
        only_missing=False,
        replace=False,
        apply=False,
        limit=None,
        **options,
    ):
        resolved_operator = self.resolve_operator(operator)
        sources = list(self.get_sources(resolved_operator, source))
        if not sources:
            raise CommandError("No matching timetable data sources found.")

        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: writing service/operator mappings.")
        )

        totals = Counter()
        remaining = limit

        with transaction.atomic():
            for timetable_source in sources:
                operators = list(timetable_source.operators.order_by("noc"))
                if not operators:
                    totals["sources_without_operators"] += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping {timetable_source} ({timetable_source.id}): no operators linked."
                        )
                    )
                    continue

                service_ids = self.get_service_ids_for_source(
                    timetable_source, only_missing
                )
                if remaining is not None:
                    service_ids = service_ids[:remaining]
                services = Service.objects.filter(id__in=service_ids).prefetch_related(
                    "operator"
                )
                service_count = services.count()
                if not service_count:
                    continue

                operator_nocs = [op.noc for op in operators]
                self.stdout.write(
                    f"{timetable_source} ({timetable_source.id}) -> {', '.join(operator_nocs)}: {service_count} services"
                )

                for service in services:
                    label, current_operators = self.describe_service(service)
                    if replace:
                        new_operators = operator_nocs
                        action = "set"
                    else:
                        current = set(service.operator.values_list("noc", flat=True))
                        new_operators = [
                            noc for noc in operator_nocs if noc not in current
                        ]
                        action = "add"
                        if not new_operators:
                            totals["unchanged"] += 1
                            continue

                    totals["services_changed"] += 1
                    self.stdout.write(
                        f"  {action} {', '.join(new_operators)} on {label}"
                        + (
                            f" (currently {current_operators})"
                            if current_operators
                            else ""
                        )
                    )

                    if apply:
                        if replace:
                            service.operator.set(operators)
                        else:
                            service.operator.add(*operators)

                if apply and len(operators) == 1:
                    trip_count = Trip.objects.filter(
                        route__source__source=timetable_source
                    ).exclude(operator=operators[0]).update(operator=operators[0])
                    totals["trips_updated"] += trip_count
                    if trip_count:
                        self.stdout.write(
                            f"  updated {trip_count} trips to {operators[0].noc}"
                        )

                totals["sources_processed"] += 1
                totals["services_seen"] += service_count
                if remaining is not None:
                    remaining -= service_count
                    if remaining <= 0:
                        break

            if not apply:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "Processed {sources_processed} sources, saw {services_seen} services, "
                "changed {services_changed}, unchanged {unchanged}, trips updated {trips_updated}.".format(
                    sources_processed=totals["sources_processed"],
                    services_seen=totals["services_seen"],
                    services_changed=totals["services_changed"],
                    unchanged=totals["unchanged"],
                    trips_updated=totals["trips_updated"],
                )
            )
        )
