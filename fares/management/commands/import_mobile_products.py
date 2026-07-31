import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from busstops.data_changes import record_applied_change
from busstops.models import Operator

from ...models import Ticket


def clean_text(value):
    text = (value or "").strip()
    return text.replace("\u00c2\u00a3", "\u00a3")


def price_from_pence(value):
    pennies = int(value or 0)
    return (Decimal(pennies) / Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


class Command(BaseCommand):
    help = "Import mobile ticket products from a CSV export into manual Ticket records."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", help="Path to the mobile products CSV export.")
        parser.add_argument(
            "--operator",
            required=True,
            help="Operator NOC, slug, or exact name to attach imported tickets to.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and summarise the CSV without writing ticket records.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_path"]).expanduser()
        if not csv_path.exists():
            raise CommandError(f"CSV file does not exist: {csv_path}")

        operator = self.resolve_operator(options["operator"])

        rows = list(self.read_rows(csv_path))
        if not rows:
            raise CommandError("CSV file did not contain any product rows.")

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run: parsed {len(rows)} products for operator {operator}."
                )
            )
            return

        created = 0
        updated = 0

        with transaction.atomic():
            for row in rows:
                ticket, was_created = self.upsert_ticket(operator, row, str(csv_path))
                if was_created:
                    created += 1
                else:
                    updated += 1
                self.stdout.write(f"{'Created' if was_created else 'Updated'} {ticket}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(rows)} mobile products for {operator}: "
                f"{created} created, {updated} updated."
            )
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

    def read_rows(self, csv_path):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as open_file:
            reader = csv.DictReader(open_file)
            for row in reader:
                category_title = clean_text(row.get("category_title"))
                topup_title = clean_text(row.get("topup_title"))
                if not category_title or not topup_title:
                    continue
                yield {
                    "ticket_type": category_title,
                    "name": topup_title,
                    "description": self.build_description(row),
                    "adult_price": self.get_adult_price(row),
                    "child_price": self.get_child_price(row),
                    "days_valid_for": self.get_days_valid_for(row),
                }

    def build_description(self, row):
        parts = []
        category_description = clean_text(row.get("category_description"))
        topup_description = clean_text(row.get("topup_description"))
        passenger_name = clean_text(row.get("topup_passenger_class_name"))
        passenger_quantity = clean_text(row.get("topup_passenger_class_quantity"))
        entitlement_quantity = clean_text(row.get("topup_entitlement_quantity"))
        entitlement_unit = clean_text(row.get("topup_entitlement_unit"))
        entitlement_value = clean_text(row.get("topup_entitlement_value"))
        price = price_from_pence(row.get("topup_price_in_pence"))

        if category_description:
            parts.append(category_description)
        if topup_description and topup_description != category_description:
            parts.append(topup_description)

        passenger_detail = passenger_name or "Passenger"
        if passenger_quantity and passenger_quantity != "1":
            passenger_detail = f"{passenger_detail} x{passenger_quantity}"
        parts.append(f"Passenger class: {passenger_detail}.")
        parts.append(f"Price: \u00a3{price}.")

        if entitlement_quantity and entitlement_quantity != "1":
            parts.append(f"Includes {entitlement_quantity} activations.")
        elif entitlement_unit and entitlement_value:
            parts.append(f"Validity: {entitlement_value} {entitlement_unit}.")

        return " ".join(part for part in parts if part)

    def get_days_valid_for(self, row):
        unit = clean_text(row.get("topup_entitlement_unit")).lower()
        value = clean_text(row.get("topup_entitlement_value"))
        quantity = clean_text(row.get("topup_entitlement_quantity"))
        if unit != "days" or quantity not in {"", "1"} or not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def get_adult_price(self, row):
        passenger_name = clean_text(row.get("topup_passenger_class_name")).lower()
        if passenger_name not in {"adult", "adults"}:
            return None
        return price_from_pence(row.get("topup_price_in_pence"))

    def get_child_price(self, row):
        passenger_name = clean_text(row.get("topup_passenger_class_name")).lower()
        if passenger_name != "child":
            return None
        return price_from_pence(row.get("topup_price_in_pence"))

    def upsert_ticket(self, operator, row, csv_path):
        ticket = Ticket.objects.filter(
            operator=operator,
            ticket_type=row["ticket_type"],
            name=row["name"],
        ).first()

        payload = {
            "csv_path": csv_path,
            "ticket_type": row["ticket_type"],
            "name": row["name"],
        }

        if ticket is None:
            ticket = Ticket.objects.create(
                operator=operator,
                ticket_type=row["ticket_type"],
                name=row["name"],
                description=row["description"],
                adult_price=row["adult_price"],
                child_price=row["child_price"],
                days_valid_for=row["days_valid_for"],
            )
            record_applied_change(
                source="import_mobile_products",
                instance=ticket,
                operation="create",
                changes={
                    "operator": {"from": None, "to": operator.noc},
                    "ticket_type": {"from": None, "to": row["ticket_type"]},
                    "name": {"from": None, "to": row["name"]},
                    "description": {"from": None, "to": row["description"]},
                    "adult_price": {"from": None, "to": row["adult_price"]},
                    "child_price": {"from": None, "to": row["child_price"]},
                    "days_valid_for": {"from": None, "to": row["days_valid_for"]},
                },
                payload=payload,
            )
            return ticket, True

        changes = {}
        for field_name in ("description", "adult_price", "child_price", "days_valid_for"):
            old_value = getattr(ticket, field_name)
            new_value = row[field_name]
            if old_value != new_value:
                changes[field_name] = {"from": old_value, "to": new_value}
                setattr(ticket, field_name, new_value)

        if changes:
            ticket.save(update_fields=sorted(changes))
            record_applied_change(
                source="import_mobile_products",
                instance=ticket,
                operation="update",
                changes=changes,
                payload=payload,
            )

        return ticket, False
