import json
import re
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from busstops.models import Operator
from vehicles.models import Livery, Vehicle, VehicleType


HEX_COLOUR_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?")


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def first_colour(css):
    match = HEX_COLOUR_RE.search(css or "")
    if not match:
        return "#000000"

    colour = match.group(0).lower()
    if len(colour) == 4:
        return "#" + "".join(char * 2 for char in colour[1:])
    return colour


def canonical_css(css):
    return Livery.minify(clean(css))


def operator_code(name):
    words = re.findall(r"[A-Za-z0-9]+", name)
    code = "".join(word[0] for word in words if word)[:10].upper()
    if len(code) < 3:
        code = "".join(words).upper()[:10]
    if not code:
        code = "TRAIN"

    candidate = code
    suffix = 1
    while Operator.objects.filter(noc=candidate).exists():
        suffix_text = str(suffix)
        candidate = f"{code[: 10 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate


class Command(BaseCommand):
    help = "Import train vehicle JSON into operators, types, liveries, and vehicles."

    def add_arguments(self, parser):
        parser.add_argument("json_file", type=Path)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read and validate the file without saving changes.",
        )

    def handle(self, *args, **options):
        path = options["json_file"]
        dry_run = options["dry_run"]

        try:
            with path.open(encoding="utf-8") as file:
                data = json.load(file)
        except OSError as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(f"{path} is not valid JSON: {exc}") from exc

        if isinstance(data, dict):
            data = data.get("trains") or data.get("vehicles") or data.get("results")
        if not isinstance(data, list):
            raise CommandError(
                "JSON must be a list, or an object containing trains, vehicles, or results."
            )

        stats = {
            "operators_created": 0,
            "types_created": 0,
            "liveries_created": 0,
            "liveries_published": 0,
            "vehicles_created": 0,
            "vehicles_updated": 0,
            "vehicles_skipped": 0,
        }

        with (
            patch.object(cache, "set", lambda *args, **kwargs: None),
            patch.object(cache, "delete", lambda *args, **kwargs: None),
            transaction.atomic(),
        ):
            for index, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    raise CommandError(f"Item {index} is not an object.")

                operator_name = clean(item.get("operator"))
                fleet_number = clean(
                    item.get("fleetnumber")
                    or item.get("fleet_number")
                    or item.get("fleet_code")
                    or item.get("code")
                )
                type_name = clean(item.get("type"))
                livery_data = item.get("livery") or {}
                livery_name = clean(livery_data.get("name"))
                livery_css = clean(livery_data.get("css"))

                if not operator_name:
                    raise CommandError(f"Item {index} is missing operator.")
                if not fleet_number:
                    raise CommandError(f"Item {index} is missing fleetnumber.")
                if not type_name:
                    raise CommandError(f"Item {index} is missing type.")

                operator, created = self.get_operator(operator_name)
                if created:
                    stats["operators_created"] += 1

                vehicle_type, created = VehicleType.objects.get_or_create(
                    name=type_name,
                    defaults={"style": "train", "is_manual": True},
                )
                if created:
                    stats["types_created"] += 1

                livery = None
                if livery_name or livery_css:
                    livery, created = self.get_livery(livery_name, livery_css)
                    if created:
                        stats["liveries_created"] += 1
                        stats["liveries_published"] += 1
                    elif livery and not livery.published:
                        livery.published = True
                        livery.save(update_fields=["published"])
                        stats["liveries_published"] += 1

                vehicle, created = Vehicle.objects.get_or_create(
                    operator=operator,
                    code=fleet_number,
                    defaults={
                        "fleet_code": fleet_number,
                        "vehicle_type": vehicle_type,
                        "livery": livery,
                        "is_manual": True,
                    },
                )

                if created:
                    stats["vehicles_created"] += 1
                    continue

                changed_fields = []
                for field, value in (
                    ("fleet_code", fleet_number),
                    ("vehicle_type", vehicle_type),
                    ("livery", livery),
                ):
                    if getattr(vehicle, field) != value:
                        setattr(vehicle, field, value)
                        changed_fields.append(field)

                if changed_fields:
                    vehicle.save(update_fields=changed_fields)
                    stats["vehicles_updated"] += 1
                else:
                    stats["vehicles_skipped"] += 1

            if dry_run:
                transaction.set_rollback(True)

        prefix = "Dry run: " if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(
                prefix
                + ", ".join(f"{key}={value}" for key, value in stats.items())
            )
        )

    def get_operator(self, name):
        operator = Operator.objects.filter(name__iexact=name).first()
        if operator:
            return operator, False

        operator = Operator.objects.create(
            noc=operator_code(name),
            name=name,
            vehicle_mode="train",
        )
        return operator, True

    def get_livery(self, name, css):
        css = clean(css)
        minified_css = canonical_css(css)

        for livery in Livery.objects.filter(name=name):
            existing_css = clean(livery.left_css)
            if existing_css in {css, minified_css}:
                return livery, False
            if canonical_css(existing_css) == minified_css:
                return livery, False

        return Livery.objects.create(
            name=name,
            colour=first_colour(css),
            left_css=minified_css,
            right_css=minified_css,
            is_manual=True,
            published=True,
        ), True
