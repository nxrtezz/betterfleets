from django.db import transaction
import re

from busstops.bustimes_sync import apply_sync_fields, compact_text
from busstops.models import Service, ServiceCode

from ._sync_bustimes import (
    BUSTIMES_SCHEME,
    BUSTIMES_SLUG_SCHEME,
    BustimesSyncCommand,
    api_id,
    resolve_operator,
    resolve_region,
)


SLUG_LINE_NAME_RE = re.compile(r"^([A-Za-z0-9]+)(?:-|$)")


class Command(BustimesSyncCommand):
    help = "Sync services from the Bustimes API."
    endpoint = "services/"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--operator",
            help="Operator NOC/code filter for service sync requests.",
        )

    def get_query_params(self, options):
        params = super().get_query_params(options)
        operator = compact_text(options.get("operator"))
        if operator:
            params["operator"] = operator
        return params

    def infer_line_name(self, item):
        line_name = compact_text(item.get("line_name"))
        if line_name:
            return line_name

        slug = compact_text(item.get("slug"))
        if not slug:
            return ""

        match = SLUG_LINE_NAME_RE.match(slug)
        if match:
            return match.group(1).upper()
        return ""

    def find_service(self, item):
        external_id = api_id(item)
        code = ServiceCode.objects.filter(
            scheme=BUSTIMES_SCHEME, code=external_id
        ).select_related("service").first()
        if code:
            return code.service

        slug = compact_text(item.get("slug"))
        if slug:
            code = ServiceCode.objects.filter(
                scheme=BUSTIMES_SLUG_SCHEME, code=slug
            ).select_related("service").first()
            if code:
                return code.service

        operators = [resolve_operator(value) for value in item.get("operator") or []]
        operators = [operator for operator in operators if operator]
        line_name = compact_text(item.get("line_name"))
        if operators and line_name:
            service = Service.objects.filter(
                operator__in=operators,
                current=True,
                line_name__iexact=line_name,
            ).first()
            if service:
                return service

    def has_existing_operator_service_code(self, item):
        service_code = compact_text(item.get("service_code"))
        if not service_code:
            return False

        operators = [resolve_operator(value) for value in item.get("operator") or []]
        operators = [operator for operator in operators if operator]
        if not operators:
            return False

        return (
            Service.objects.filter(
                operator__in=operators,
                current=True,
            )
            .filter(service_code__iexact=service_code)
            .exists()
        )

    def values_from_item(self, item):
        line_name = self.infer_line_name(item)
        return {
            "service_code": compact_text(
                item.get("service_code") or line_name or api_id(item)
            ),
            "line_name": line_name,
            "description": compact_text(item.get("description")),
            "region": resolve_region(item.get("region_id")),
            "mode": compact_text(item.get("mode")) or "bus",
            "current": True,
            "source": self.get_source(),
        }

    @transaction.atomic
    def sync_item(self, item, options):
        service = self.find_service(item)
        if service is None and self.has_existing_operator_service_code(item):
            return False, False, 1

        service = service or Service()
        result = apply_sync_fields(
            instance=service,
            object_type="service",
            external_id=api_id(item),
            values=self.values_from_item(item),
            payload=item,
            dry_run=options["dry_run"],
            force=options["force"],
        )

        if not options["dry_run"] and service.pk:
            for scheme, code in (
                (BUSTIMES_SCHEME, api_id(item)),
                (BUSTIMES_SLUG_SCHEME, compact_text(item.get("slug"))),
            ):
                if code and not service.servicecode_set.filter(
                    scheme=scheme, code=code
                ).exists():
                    ServiceCode.objects.create(service=service, scheme=scheme, code=code)

            operators = [resolve_operator(value) for value in item.get("operator") or []]
            operators = [operator for operator in operators if operator]
            if operators:
                service.operator.set(operators)

        return result.created, result.updated, len(result.skipped_fields)

    def handle(self, *args, **options):
        created = updated = skipped = 0
        progress = self.progress(options)
        for item in self.iter_items_with_progress(options, progress):
            item_created, item_updated, item_skipped = self.sync_item(item, options)
            created += int(item_created)
            updated += int(item_updated)
            skipped += item_skipped
            progress.tick(created=item_created, updated=item_updated, skipped=item_skipped)
        self.print_summary(created, updated, skipped)
