from collections import Counter

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from busstops.models import Operator, Service
from busstops.views import (
    get_bustimes_base_url,
    link_bustimes_service,
    resolve_bustimes_service_identifier,
)
from ._sync_bustimes import ProgressBar, resolve_operator, resolve_region


def compact_text(value):
    return str(value or "").strip()


class Command(BaseCommand):
    help = (
        "Audit bustimes-linked services against the bustimes API, delete ones "
        "that no longer exist upstream, and refresh mismatched local details."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            help="Optional operator NOC, slug, or exact name.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write service updates and deletions. Without this flag the command is audit-only.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Only process this many services.",
        )
        parser.add_argument(
            "--progress",
            action="store_true",
            help="Force progress output.",
        )
        parser.add_argument(
            "--no-progress",
            action="store_true",
            help="Disable progress output.",
        )

    def resolve_operator(self, value):
        operator = (
            Operator.objects.filter(noc__iexact=value).first()
            or Operator.objects.filter(slug__iexact=value).first()
            or Operator.objects.filter(name__iexact=value).first()
        )
        if not operator:
            raise CommandError(f"Could not find operator matching {value!r}")
        return operator

    def get_services(self, operator):
        queryset = Service.objects.filter(
            current=True,
            servicecode__scheme__in=("bustimes", "bustimes-slug"),
        )
        if operator:
            queryset = queryset.filter(operator=operator)
        return (
            queryset
            .annotate(
                stop_usage_count=Count("stopusage", distinct=True),
                route_count=Count("route", distinct=True),
            )
            .prefetch_related("servicecode_set", "operator")
            .distinct()
            .order_by("line_name", "description", "id")
        )

    def show_progress(self, options):
        if options.get("no_progress"):
            return False
        if options.get("progress"):
            return True
        isatty = getattr(self.stdout, "isatty", None)
        return bool(isatty and isatty())

    def get_slug_candidates(self, service, identifier=None):
        candidates = [
            compact_text(
                service.servicecode_set.filter(scheme="bustimes-slug")
                .values_list("code", flat=True)
                .first()
            ),
            compact_text(identifier),
            compact_text(service.slug),
        ]
        return [value for value in dict.fromkeys(candidates) if value]

    def fetch_service_list_item_by_slug(self, slug):
        if not slug:
            return None, "no slug"

        try:
            response = requests.get(
                f"{get_bustimes_base_url()}/api/services/",
                params={"slug": slug},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return None, str(exc)

        for item in payload.get("results", []):
            if compact_text(item.get("slug")).casefold() == slug.casefold():
                return item, None
        return None, "404"

    def sync_service_details(self, service, item):
        changed_fields = []

        updates = {
            "service_code": compact_text(item.get("service_code") or item.get("id")),
            "line_name": compact_text(item.get("line_name")),
            "description": compact_text(item.get("description")),
            "mode": compact_text(item.get("mode")) or "bus",
            "current": True,
            "region": resolve_region(item.get("region_id")),
        }

        for field, value in updates.items():
            if getattr(service, field) != value:
                setattr(service, field, value)
                changed_fields.append(field)

        remote_slug = compact_text(item.get("slug"))
        if remote_slug and compact_text(service.slug) != remote_slug:
            service.slug = remote_slug
            changed_fields.append("slug")

        if changed_fields:
            service.save(update_fields=[*changed_fields, "modified_at"])

        operators = [resolve_operator(value) for value in item.get("operator") or []]
        operators = [operator for operator in operators if operator]
        if operators:
            current_operator_ids = list(service.operator.order_by("pk").values_list("pk", flat=True))
            new_operator_ids = sorted(operator.pk for operator in operators)
            if current_operator_ids != new_operator_ids:
                service.operator.set(operators)
                changed_fields.append("operator")

        link_bustimes_service(service, item)
        return changed_fields

    def fetch_bustimes_service_item(self, service):
        identifier = resolve_bustimes_service_identifier(service)
        slug_candidates = self.get_slug_candidates(service, identifier)
        if not slug_candidates:
            return None, "no bustimes slug"

        service_item, error = self.fetch_service_list_item_by_slug(slug_candidates[0])
        if error == "404":
            return None, "404"
        if error:
            return None, error
        return service_item, None

    def handle(self, *args, operator=None, apply=False, limit=None, **options):
        operator_obj = self.resolve_operator(operator) if operator else None
        services = list(self.get_services(operator_obj))
        if limit:
            services = services[:limit]

        totals = Counter()
        if not apply:
            self.stdout.write(self.style.WARNING("Dry run: no changes will be written."))

        progress = ProgressBar(self, enabled=self.show_progress(options))
        progress.start(total=len(services), url="local bustimes-linked services")

        for service in services:
            totals["services_seen"] += 1
            changed_fields = []
            service_item, error = self.fetch_bustimes_service_item(service)
            if error:
                if error == "404":
                    totals["services_404"] += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"{service.id} {service}: bustimes service now returns 404"
                        )
                    )
                    if apply:
                        service.delete()
                        totals["services_deleted"] += 1
                        progress.tick(updated=1)
                    else:
                        progress.tick(skipped=1)
                    continue
                totals["fetch_errors"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"{service.id} {service}: could not fetch bustimes service details ({error})"
                    )
                )
                progress.tick(skipped=1)
                continue

            if apply and service_item:
                changed_fields = self.sync_service_details(service, service_item)
                if changed_fields:
                    totals["services_details_updated"] += 1
                    self.stdout.write(
                        f"  updated service details: {', '.join(changed_fields)}"
                    )
            else:
                local_slug = compact_text(service.slug)
                remote_slug = compact_text(service_item.get("slug"))
                remote_line_name = compact_text(service_item.get("line_name"))
                remote_description = compact_text(service_item.get("description"))
                if (
                    local_slug.casefold() != remote_slug.casefold()
                    or compact_text(service.line_name) != remote_line_name
                    or compact_text(service.description) != remote_description
                ):
                    totals["services_details_mismatched"] += 1

            progress.tick(updated=int(bool(apply and changed_fields)))

        progress.finish()

        self.stdout.write(
            self.style.SUCCESS(
                "Seen {services_seen} services, details updated {services_details_updated}, "
                "details mismatched {services_details_mismatched}, "
                "404s {services_404}, deleted {services_deleted}, fetch errors {fetch_errors}.".format(
                    services_seen=totals["services_seen"],
                    services_details_updated=totals["services_details_updated"],
                    services_details_mismatched=totals["services_details_mismatched"],
                    services_404=totals["services_404"],
                    services_deleted=totals["services_deleted"],
                    fetch_errors=totals["fetch_errors"],
                )
            )
        )
