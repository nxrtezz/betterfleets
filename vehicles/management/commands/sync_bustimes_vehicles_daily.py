import logging
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from busstops.models import DataSource, Operator
from bustimes.models import Garage
from vehicles.models import Livery, Vehicle, VehicleType


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Daily sync of vehicles from Bustimes API - only processes if count changes"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Force sync even if count hasn't changed")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")

    def handle(self, *args, **options):
        force = options.get("force", False)
        dry_run = options.get("dry_run", False)

        # Get API URL from settings or use default
        base_url = getattr(settings, "BUSTIMES_API_BASE_URL", "https://bustimes.org/").strip()
        if not base_url.endswith("/"):
            base_url += "/"

        # Ensure /api/ is in the path
        if not base_url.endswith("/api/"):
            base_url = urljoin(base_url, "api/")

        # Fetch vehicles with withdrawn=false
        url = urljoin(base_url, "vehicles/")
        params = {"withdrawn": "false"}

        self.stdout.write(f"Fetching vehicles from {url}?withdrawn=false")

        # First fetch to get total count
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            raise CommandError(f"Failed to fetch vehicles from API: {e}")

        data = response.json()

        # Handle both list and paginated response formats
        if isinstance(data, dict):
            count = data.get("count", 0)
            vehicles = data.get("results", [])
        elif isinstance(data, list):
            count = len(data)
            vehicles = data
        else:
            raise CommandError(f"Unexpected API response format: {type(data)}")

        self.stdout.write(f"API returned {count} total vehicles")

        # Fetch all vehicles using pagination
        all_vehicles = list(vehicles)
        offset = 100

        while len(all_vehicles) < count:
            params["offset"] = offset
            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
            except requests.RequestException as e:
                raise CommandError(f"Failed to fetch vehicles from API (offset {offset}): {e}")

            data = response.json()
            if isinstance(data, dict):
                vehicles = data.get("results", [])
            else:
                vehicles = data

            if not vehicles:
                break

            all_vehicles.extend(vehicles)
            self.stdout.write(f"Fetched {len(all_vehicles)}/{count} vehicles...")
            offset += 100

        vehicles = all_vehicles

        # Check if count has changed
        cache_key = "bustimes_vehicle_count"
        last_count = cache.get(cache_key)

        if not force and last_count == count:
            self.stdout.write(self.style.SUCCESS(f"Count unchanged ({count}), skipping sync"))
            return

        if last_count is None:
            self.stdout.write(f"No previous count stored, proceeding with sync")
        else:
            self.stdout.write(self.style.WARNING(f"Count changed from {last_count} to {count}, proceeding with sync"))

        # Update cached count
        cache.set(cache_key, count, 86400)  # Cache for 24 hours

        # Process vehicles
        created_count = 0
        skipped_count = 0
        error_count = 0

        # Get or create data source
        source, _ = DataSource.objects.get_or_create(
            name="Bustimes Daily Sync",
            defaults={"url": base_url}
        )

        for item in vehicles:
            try:
                reg = self._normalize_reg(item.get("reg"))
                
                if not reg:
                    skipped_count += 1
                    continue

                # Check if vehicle already exists by reg
                existing_vehicle = Vehicle.objects.filter(reg__iexact=reg).first()

                if existing_vehicle:
                    skipped_count += 1
                    continue

                # Vehicle doesn't exist, create it
                if dry_run:
                    self.stdout.write(f"Would create vehicle with reg: {reg}")
                    created_count += 1
                    continue

                # Resolve related objects
                operator = self._resolve_operator(item.get("operator"))
                vehicle_type = self._resolve_vehicle_type(item.get("vehicle_type"))
                livery = self._resolve_livery(item.get("livery"))
                garage = self._resolve_garage(item.get("garage"), operator)

                # Create vehicle
                vehicle = Vehicle(
                    code=item.get("fleet_code") or item.get("slug") or reg,
                    fleet_number=item.get("fleet_number"),
                    fleet_code=item.get("fleet_code") or "",
                    reg=reg,
                    prev_registration=self._normalize_reg(item.get("previous_reg")),
                    vehicle_type=vehicle_type,
                    livery=livery,
                    garage=garage,
                    branding=item.get("branding") or "",
                    name=item.get("name") or "",
                    notes=item.get("notes") or "",
                    withdrawn=bool(item.get("withdrawn", False)),
                    operator=operator,
                    external_id=item.get("id"),
                    source=source,
                )
                vehicle.save()
                created_count += 1
                self.stdout.write(f"Created vehicle: {reg}")

            except Exception as e:
                error_count += 1
                logger.exception(f"Error processing vehicle: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync complete: {created_count} created, {skipped_count} skipped, {error_count} errors"
            )
        )

    @staticmethod
    def _normalize_reg(value):
        if not value:
            return ""
        return str(value).upper().replace(" ", "")

    @staticmethod
    def _resolve_operator(value):
        if not value:
            return None
        if isinstance(value, dict):
            value = value.get("id") or value.get("slug")
        if not value:
            return None
        return Operator.objects.filter(Q(pk=value) | Q(slug=value)).first()

    @staticmethod
    def _resolve_vehicle_type(value):
        if not value:
            return None
        if isinstance(value, dict):
            name = value.get("name")
            value = value.get("external_id") or value.get("id") or name
        if not value:
            return None
        value = str(value)
        obj = VehicleType.objects.filter(external_id=value).first()
        if obj:
            return obj
        if value.isdigit():
            obj = VehicleType.objects.filter(pk=int(value)).first()
            if obj:
                return obj
        return VehicleType.objects.filter(name__iexact=value).first()

    @staticmethod
    def _resolve_livery(value):
        if not value:
            return None
        if isinstance(value, dict):
            name = value.get("name")
            value = value.get("external_id") or value.get("id") or name
        if not value:
            return None
        value = str(value)
        obj = Livery.objects.filter(external_id=value).first()
        if obj:
            return obj
        if value.isdigit():
            obj = Livery.objects.filter(pk=int(value)).first()
            if obj:
                return obj
        return Livery.objects.filter(name__iexact=value).first()

    @staticmethod
    def _resolve_garage(value, operator=None):
        if not value:
            return None
        if isinstance(value, dict):
            external_id = value.get("id")
            code = value.get("code") or ""
            garage = None
            if external_id:
                garage = Garage.objects.filter(external_id=external_id).first()
            if not garage and operator and code:
                garage = Garage.objects.filter(operator=operator, code__iexact=code).first()
            if not garage and code:
                garage = Garage.objects.filter(code__iexact=code).first()
            if garage:
                return garage
            # Create garage if it doesn't exist
            if code or external_id:
                return Garage.objects.create(
                    code=code,
                    name=value.get("name") or "",
                    operator=operator,
                    external_id=external_id,
                )
            return None
        if str(value).isdigit():
            return Garage.objects.filter(pk=int(value)).first()
        return Garage.objects.filter(external_id=str(value)).first()
