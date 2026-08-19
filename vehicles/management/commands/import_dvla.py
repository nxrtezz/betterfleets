import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from tqdm import tqdm

from busstops.models import Operator, OperatorGroup, Organisation
from vehicles.dvla import (
    DEFAULT_DVLA_URL,
    DEFAULT_DVLA_USER_AGENT,
    build_dvla_update,
    fetch_dvla_record,
)
from vehicles.models import Vehicle


class Command(BaseCommand):
    help = "Import DVLA tax and euro status data for vehicles in an operator, organisation, or operator group."

    def add_arguments(self, parser):
        parser.add_argument("--operator", help="Operator NOC to query.")
        parser.add_argument(
            "--organisation",
            "--organization",
            dest="organisation",
            help="Organisation slug to query.",
        )
        parser.add_argument(
            "--operator-group",
            "--operator_group",
            dest="operator_group",
            help="Operator group slug to query.",
        )
        parser.add_argument(
            "--api_key",
            help="DVLA Vehicle Enquiry API key. Falls back to settings if omitted.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the previewed DVLA data without an interactive confirmation prompt.",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=2,
            help="Number of parallel workers for DVLA lookups. Default: 2.",
        )

    def handle(self, *args, **options):
        api_key = options["api_key"] or getattr(settings, "DVLA_VEHICLE_ENQUIRY_API_KEY", "")
        if not api_key:
            raise CommandError("Provide --api_key or set DVLA_VEHICLE_ENQUIRY_API_KEY.")

        scope_label, vehicles = self._resolve_scope(options)
        workers = options["workers"]

        checked_at = timezone.now()
        url = getattr(settings, "DVLA_VEHICLE_ENQUIRY_URL", DEFAULT_DVLA_URL)
        user_agent = getattr(
            settings,
            "DVLA_VEHICLE_ENQUIRY_USER_AGENT",
            DEFAULT_DVLA_USER_AGENT,
        )

        vehicles = list(
            vehicles.exclude(reg="").order_by("fleet_number", "fleet_code", "reg", "code")
        )
        if not vehicles:
            self.stdout.write(f"No eligible vehicles found for {scope_label}.")
            return

        updates = []
        failures = []

        lookup_progress = tqdm(
            total=len(vehicles),
            desc="DVLA lookups",
            unit="vehicle",
            file=self.stdout,
            disable=not vehicles,
        )

        def fetch_vehicle(vehicle):
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    payload = fetch_dvla_record(
                        vehicle.reg,
                        api_key=api_key,
                        url=url,
                        user_agent=user_agent,
                    )
                    return ("success", vehicle, payload)
                except Exception as exc:
                    error_msg = str(exc).lower()
                    if "too many requests" in error_msg:
                        if attempt < max_retries - 1:
                            wait_time = 60 * (attempt + 1)
                            time.sleep(wait_time)
                            continue
                    return ("failure", vehicle, str(exc))
            return ("failure", vehicle, "Max retries exceeded")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch_vehicle, vehicle): vehicle for vehicle in vehicles}
            for future in as_completed(futures):
                status, vehicle, result = future.result()
                if status == "success":
                    updates.append(build_dvla_update(vehicle, result, checked_at=checked_at))
                else:
                    failures.append((vehicle, result))
                lookup_progress.update(1)

        self._write_preview(scope_label, updates, failures)

        if not updates:
            self.stdout.write("No DVLA updates were returned, so nothing will be changed.")
            return

        if options["apply"]:
            self._apply_updates(updates)
            return

        if self._confirm_apply():
            self._apply_updates(updates)
        else:
            self.stdout.write("Cancelled. No DVLA data was applied.")

    def _resolve_scope(self, options):
        provided = [
            bool(options.get("operator")),
            bool(options.get("organisation")),
            bool(options.get("operator_group")),
        ]
        if sum(provided) > 1:
            raise CommandError(
                "Provide at most one of --operator, --organisation, or --operator-group."
            )

        if not any(provided):
            return "all vehicles", Vehicle.objects.all()

        if options.get("operator"):
            operator = Operator.objects.filter(noc__iexact=options["operator"]).first()
            if not operator:
                raise CommandError(f"Operator {options['operator']} was not found.")
            return f"{operator.noc} - {operator.name}", Vehicle.objects.filter(operator=operator)

        if options.get("organisation"):
            organisation = Organisation.objects.filter(slug=options["organisation"]).first()
            if not organisation:
                raise CommandError(f"Organisation {options['organisation']} was not found.")
            return (
                f"organisation {organisation.slug} - {organisation.name}",
                Vehicle.objects.filter(operator__organisation=organisation),
            )

        operator_group = OperatorGroup.objects.filter(slug=options["operator_group"]).first()
        if not operator_group:
            raise CommandError(f"Operator group {options['operator_group']} was not found.")
        return (
            f"operator group {operator_group.slug} - {operator_group.name}",
            Vehicle.objects.filter(operator__group=operator_group),
        )

    def _write_preview(self, scope_label, updates, failures):
        self.stdout.write(f"DVLA preview for {scope_label}")
        self.stdout.write(
            "Vehicle | Registration | Current tax -> New tax | Current MOT -> New MOT | Current euro -> New euro | Year of manufacture"
        )
        self.stdout.write("-" * 110)
        for item in updates:
            vehicle = item["vehicle"]
            label = vehicle.fleet_code or vehicle.fleet_number or vehicle.code
            self.stdout.write(
                f"{label} | {vehicle.get_reg()} | "
                f"{vehicle.dvla_tax_status or '-'} -> {item['tax_status'] or '-'} | "
                f"{vehicle.dvla_mot_status or '-'} -> {item['mot_status'] or '-'} | "
                f"{vehicle.dvla_euro_status or '-'} -> {item['euro_status'] or '-'} | "
                f"{vehicle.year_of_manufacture or '-'} -> {item['year_of_manufacture'] or '-'}"
            )
        if failures:
            self.stdout.write("")
            self.stdout.write("Lookup failures:")
            for vehicle, error in failures:
                label = vehicle.fleet_code or vehicle.fleet_number or vehicle.code
                self.stdout.write(f"- {label} ({vehicle.get_reg()}): {error}")
        self.stdout.write("")
        self.stdout.write(
            f"{len(updates)} vehicle(s) ready to update, {len(failures)} failure(s)."
        )

    def _confirm_apply(self) -> bool:
        try:
            answer = input("Apply these DVLA updates? [y/N]: ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    def _apply_updates(self, updates):
        applied = 0
        apply_progress = tqdm(
            updates,
            desc="Applying updates",
            unit="vehicle",
            file=self.stdout,
            disable=not updates,
        )
        for item in apply_progress:
            vehicle = item["vehicle"]
            vehicle.dvla_tax_status = item["tax_status"]
            vehicle.dvla_mot_status = item["mot_status"]
            vehicle.dvla_euro_status = item["euro_status"]
            vehicle.dvla_tax_status_checked_at = item["checked_at"]
            vehicle.year_of_manufacture = item["year_of_manufacture"]
            
            # Update vehicle type fuel type if mismatch
            fuel_type = item["fuel_type"]
            if fuel_type and vehicle.vehicle_type and vehicle.vehicle_type.fuel != fuel_type:
                vehicle.vehicle_type.fuel = fuel_type
                vehicle.vehicle_type.save(update_fields=["fuel"])
            
            vehicle.save(
                update_fields=[
                    "dvla_tax_status",
                    "dvla_mot_status",
                    "dvla_euro_status",
                    "dvla_tax_status_checked_at",
                    "year_of_manufacture",
                ]
            )
            applied += 1
        self.stdout.write(self.style.SUCCESS(f"Applied DVLA data to {applied} vehicle(s)."))
