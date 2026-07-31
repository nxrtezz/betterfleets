from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify

from busstops.fields import generate_unique_slug
from busstops.models import Operator
from vehicles.models import Vehicle, vehicle_slug


class Command(BaseCommand):
    help = (
        "Split vehicles out of the National Express fleet (NATX) based on their "
        "vehicle notes. Dry-run by default; pass --apply to write changes."
    )

    national_express_aliases = {
        "national express",
        "national express west midlands",
        "national express coventry",
        "national express dundee",
        "national express transport solutions",
        "nx",
        "n x",
        "natx",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only reports actions.",
        )

    def normalise_name(self, value):
        return " ".join((value or "").strip().lower().split())

    def is_national_express_alias(self, value):
        normalised = self.normalise_name(value)
        return bool(normalised) and (
            normalised in self.national_express_aliases
            or normalised.startswith("national express ")
            or normalised.startswith("nx ")
        )

    def build_base_noc(self, name):
        words = [word for word in slugify(name).upper().split("-") if word]
        initials = "".join(word[0] for word in words)
        if len(initials) >= 4:
            return initials[:4]

        letters = "".join(words)
        candidate = (initials + letters)[:4]
        if len(candidate) < 4:
            candidate = candidate.ljust(4, "X")
        return candidate

    def get_unique_noc(self, name):
        base_noc = self.build_base_noc(name)
        if not Operator.objects.filter(noc=base_noc).exists():
            return base_noc

        for suffix in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            candidate = f"{base_noc[:3]}{suffix}"
            if not Operator.objects.filter(noc=candidate).exists():
                return candidate

        raise CommandError(f"Could not generate a unique NOC for {name!r}")

    def get_unique_slug(self, name):
        base_slug = slugify(name)[:50] or "operator"
        slug = base_slug
        suffix = 1
        while Operator.objects.filter(slug=slug).exists():
            suffix += 1
            slug = f"{base_slug[: max(1, 50 - len(str(suffix)) - 1)]}-{suffix}"
        return slug

    def get_or_create_target_operator(self, name, natx_operator, apply, planned_operators):
        normalised_name = self.normalise_name(name)
        if normalised_name in planned_operators:
            return planned_operators[normalised_name], False

        existing = Operator.objects.filter(name__iexact=name).first()
        if existing:
            planned_operators[normalised_name] = existing
            return existing, False

        operator = Operator(
            noc=self.get_unique_noc(name),
            name=name,
            slug=self.get_unique_slug(name),
            region=natx_operator.region,
            source=natx_operator.source,
            vehicle_mode=natx_operator.vehicle_mode,
        )
        planned_operators[normalised_name] = operator
        if apply:
            operator.save()
        return operator, True

    def update_vehicle_slug(self, vehicle):
        slug_field = vehicle._meta.get_field("slug")
        base_slug = slugify(vehicle_slug(vehicle))
        vehicle.slug = generate_unique_slug(
            slug_field,
            vehicle,
            base_slug,
            Vehicle.objects.all(),
        )

    def handle(self, apply=False, **options):
        try:
            natx_operator = Operator.objects.get(noc="NATX")
        except Operator.DoesNotExist as exc:
            raise CommandError("Could not find operator NATX") from exc

        natx_vehicles = list(
            Vehicle.objects.filter(operator=natx_operator)
            .exclude(Q(reg="") & Q(notes=""))
            .order_by("id")
        )
        if not natx_vehicles:
            self.stdout.write("No NATX vehicles found.")
            return

        self.stdout.write(
            self.style.WARNING("Dry run: no changes will be written.")
            if not apply
            else self.style.SUCCESS("Apply mode: writing fleet changes.")
        )

        totals = Counter()
        planned_operators = {}

        with transaction.atomic():
            for vehicle in natx_vehicles:
                note = (vehicle.notes or "").strip()
                reg = (vehicle.reg or "").strip().upper()

                if reg:
                    duplicate_elsewhere = Vehicle.objects.filter(reg__iexact=reg).exclude(
                        operator=natx_operator
                    )
                    if duplicate_elsewhere.exists():
                        totals["deleted"] += 1
                        self.stdout.write(
                            f"delete vehicle {vehicle.id} {vehicle.code} ({reg}) from NATX: reg exists on another operator"
                        )
                        if apply:
                            vehicle.delete()
                        continue

                if not note:
                    totals["notes_cleared"] += 1
                    self.stdout.write(
                        f"clear note on vehicle {vehicle.id} {vehicle.code}: no operator note to split to"
                    )
                    if apply:
                        vehicle.notes = ""
                        vehicle.save(update_fields=["notes"])
                    continue

                if self.is_national_express_alias(note):
                    totals["notes_cleared"] += 1
                    self.stdout.write(
                        f"keep vehicle {vehicle.id} {vehicle.code} on NATX: note {note!r} is a National Express alias"
                    )
                    if apply:
                        vehicle.notes = ""
                        vehicle.save(update_fields=["notes"])
                    continue

                target_operator, created = self.get_or_create_target_operator(
                    note, natx_operator, apply, planned_operators
                )
                if created:
                    totals["operators_created"] += 1
                    self.stdout.write(
                        f"create operator {target_operator.noc} for {target_operator.name}"
                    )

                totals["moved"] += 1
                self.stdout.write(
                    f"move vehicle {vehicle.id} {vehicle.code} ({reg or 'no reg'}) to {target_operator.noc} {target_operator.name}"
                )
                if apply:
                    vehicle.operator = target_operator
                    vehicle.notes = ""
                    self.update_vehicle_slug(vehicle)
                    vehicle.save(update_fields=["operator", "notes", "slug"])

            if not apply:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "Processed {processed} NATX vehicles: moved {moved}, deleted {deleted}, "
                "created operators {operators_created}, cleared notes {notes_cleared}.".format(
                    processed=len(natx_vehicles),
                    moved=totals["moved"],
                    deleted=totals["deleted"],
                    operators_created=totals["operators_created"],
                    notes_cleared=totals["notes_cleared"],
                )
            )
        )
