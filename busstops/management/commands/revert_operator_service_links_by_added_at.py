from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from busstops.models import Operator, Service


@dataclass
class ServiceOperatorLink:
    link_id: int
    service_id: int
    line_name: str
    description: str
    added_at: object


class Command(BaseCommand):
    help = (
        "Revert Service.operator links for one operator based on when the join row "
        "was committed in PostgreSQL. Dry-run by default; pass --apply to delete."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            required=True,
            help="Operator NOC, slug, or exact name.",
        )
        parser.add_argument(
            "--added-since",
            required=True,
            help="Inclusive ISO datetime for when the operator link was added.",
        )
        parser.add_argument(
            "--added-until",
            help="Exclusive ISO datetime upper bound for when the operator link was added.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Preview or delete at most this many matching links.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete matching links. Without this flag the command only reports.",
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

    def parse_bound(self, value: str, label: str):
        parsed = parse_datetime(value)
        if parsed is None:
            raise CommandError(
                f"{label} must be an ISO datetime, for example 2026-05-10T14:30:00+01:00"
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def ensure_postgres_commit_timestamps(self):
        if connection.vendor != "postgresql":
            raise CommandError(
                "This command currently only works on PostgreSQL because it relies on "
                "pg_xact_commit_timestamp."
            )

        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('track_commit_timestamp', true)")
            row = cursor.fetchone()

        if not row or row[0] != "on":
            raise CommandError(
                "PostgreSQL track_commit_timestamp is not enabled, so the database "
                "cannot tell when these operator links were added."
            )

    def get_matching_links(self, operator, added_since, added_until=None, limit=None):
        through = Service.operator.through
        through_table = connection.ops.quote_name(through._meta.db_table)
        service_table = connection.ops.quote_name(Service._meta.db_table)

        where = [
            "link.operator_id = %s",
            "pg_xact_commit_timestamp(link.xmin) IS NOT NULL",
            "pg_xact_commit_timestamp(link.xmin) >= %s",
        ]
        params = [operator.pk, added_since]

        if added_until is not None:
            where.append("pg_xact_commit_timestamp(link.xmin) < %s")
            params.append(added_until)

        limit_clause = ""
        if limit:
            limit_clause = "LIMIT %s"
            params.append(limit)

        sql = f"""
            SELECT
                link.id,
                link.service_id,
                service.line_name,
                service.description,
                pg_xact_commit_timestamp(link.xmin) AS added_at
            FROM {through_table} link
            INNER JOIN {service_table} service ON service.id = link.service_id
            WHERE {" AND ".join(where)}
            ORDER BY pg_xact_commit_timestamp(link.xmin), link.id
            {limit_clause}
        """

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        return [
            ServiceOperatorLink(
                link_id=row[0],
                service_id=row[1],
                line_name=row[2] or "",
                description=row[3] or "",
                added_at=row[4],
            )
            for row in rows
        ]

    def handle(
        self,
        *args,
        operator,
        added_since,
        added_until=None,
        limit=None,
        apply=False,
        **options,
    ):
        self.ensure_postgres_commit_timestamps()
        operator_obj = self.resolve_operator(operator)
        since_dt = self.parse_bound(added_since, "--added-since")
        until_dt = self.parse_bound(added_until, "--added-until") if added_until else None

        if until_dt is not None and until_dt <= since_dt:
            raise CommandError("--added-until must be later than --added-since")

        links = self.get_matching_links(
            operator_obj,
            added_since=since_dt,
            added_until=until_dt,
            limit=limit,
        )

        if not links:
            self.stdout.write(self.style.WARNING("No matching operator links found."))
            return

        mode_message = (
            self.style.SUCCESS("Apply mode: deleting matching operator links.")
            if apply
            else self.style.WARNING("Dry run: no links will be deleted.")
        )
        self.stdout.write(mode_message)
        self.stdout.write(
            f"Operator {operator_obj.noc}: found {len(links)} link(s)"
            f" added since {since_dt.isoformat()}"
            + (f" and before {until_dt.isoformat()}." if until_dt else ".")
        )

        for link in links[:50]:
            label = " - ".join(
                part for part in (link.line_name, link.description) if part
            ) or f"service {link.service_id}"
            self.stdout.write(
                f"  delete link {link.link_id}: service {link.service_id} "
                f"({label}) added at {link.added_at}"
            )

        if len(links) > 50:
            self.stdout.write(
                self.style.WARNING(
                    f"Preview truncated after 50 rows; {len(links) - 50} more match."
                )
            )

        if not apply:
            return

        through = Service.operator.through
        link_ids = [link.link_id for link in links]
        with transaction.atomic():
            deleted, _ = through.objects.filter(id__in=link_ids).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} row(s) from {through._meta.db_table}."
            )
        )
