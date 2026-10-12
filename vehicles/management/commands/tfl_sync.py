from datetime import timedelta
import logging

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from busstops.bustimes_sync import BustimesApiClient
from busstops.models import Operator
from vehicles.models import Livery, Vehicle, VehicleType
from vehicles.tasks import schedule_tfl_vehicle_check

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync TFLO vehicles against bustimes.org API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--check-new",
            action="store_true",
            help="Check only vehicles created in the last 2 hours",
        )
        parser.add_argument(
            "--vehicle-id",
            type=int,
            help="Check a specific vehicle by ID",
        )

    def handle(self, *args, **options):
        # Get TFLO operator
        tflo_operator = Operator.objects.filter(noc="TFLO").first()
        if not tflo_operator:
            self.stdout.write(self.style.ERROR("TFLO operator not found"))
            return

        # Get vehicles to check
        queryset = Vehicle.objects.filter(operator=tflo_operator).exclude(reg="")
        
        if options.get("vehicle_id"):
            queryset = queryset.filter(id=options["vehicle_id"])
        elif options.get("check_new"):
            two_hours_ago = timezone.now() - timedelta(hours=2)
            queryset = queryset.filter(created_at__gte=two_hours_ago)

        vehicles = list(queryset)
        
        if not vehicles:
            self.stdout.write("No TFLO vehicles to check")
            return

        self.stdout.write(f"Checking {len(vehicles)} TFLO vehicle(s) against bustimes.org API")

        client = BustimesApiClient()
        
        updated = 0
        not_found = 0
        errors = 0

        for vehicle in vehicles:
            try:
                result = self._check_vehicle(vehicle, client)
                if result == "updated":
                    updated += 1
                elif result == "not_found":
                    not_found += 1
                elif result == "error":
                    errors += 1
            except Exception as exc:
                logger.exception("Error checking vehicle %s: %s", vehicle.id, exc)
                errors += 1

        self.stdout.write(
            f"Done: {updated} updated, {not_found} not found in API, {errors} errors"
        )

    def _check_vehicle(self, vehicle, client):
        """Check a single vehicle against bustimes.org API"""
        if not vehicle.reg:
            return "no_reg"

        # Fetch vehicle data from bustimes.org API
        try:
            params = {"reg": vehicle.reg.replace(" ", "").upper()}
            response = requests.get(
                "https://bustimes.org/api/vehicles/",
                params=params,
                timeout=10,
                headers={
                    "User-Agent": getattr(
                        settings, "BUSTIMES_API_USER_AGENT", "betterfleet/1.0"
                    )
                },
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.warning("Could not fetch Bustimes vehicle data for %s: %s", vehicle.reg, exc)
            return "error"

        if not data.get("results"):
            logger.info("Vehicle %s not found in bustimes.org API", vehicle.reg)
            return "not_found"

        bustimes_vehicle = data["results"][0]
        updated = False

        # Sync livery using name and CSS
        if bustimes_vehicle.get("livery"):
            updated |= self._sync_livery(vehicle, bustimes_vehicle["livery"])

        # Sync vehicle type using name
        if bustimes_vehicle.get("vehicle_type"):
            updated |= self._sync_vehicle_type(vehicle, bustimes_vehicle["vehicle_type"])

        if updated:
            self.stdout.write(f"Updated vehicle {vehicle.code} ({vehicle.reg})")
            return "updated"

        return "no_change"

    def _sync_livery(self, vehicle, livery_data):
        """Sync livery using name and CSS"""
        livery_name = livery_data.get("name")
        left_css = livery_data.get("left_css", "")
        right_css = livery_data.get("right_css", "")

        if not livery_name:
            return False

        # Check if vehicle already has a matching livery by name
        if vehicle.livery and vehicle.livery.name == livery_name:
            return False

        # Try to find existing livery by name
        existing_livery = Livery.objects.filter(name=livery_name).first()
        
        if existing_livery:
            # Use existing livery even if CSS differs (avoid duplicates)
            vehicle.livery = existing_livery
            vehicle.save(update_fields=["livery"])
            return True

        # Create new livery only if no livery with that name exists
        new_livery = Livery.objects.create(
            name=livery_name,
            left_css=left_css,
            right_css=right_css,
            published=True,
        )
        vehicle.livery = new_livery
        vehicle.save(update_fields=["livery"])
        logger.info("Created new livery: %s", livery_name)
        return True

    def _sync_vehicle_type(self, vehicle, vehicle_type_data):
        """Sync vehicle type using name"""
        vehicle_type_name = vehicle_type_data.get("name")
        
        if not vehicle_type_name:
            return False

        # Check if vehicle already has a matching vehicle type by name
        if vehicle.vehicle_type and vehicle.vehicle_type.name == vehicle_type_name:
            return False

        # Try to find existing vehicle type by name
        existing_type = VehicleType.objects.filter(name=vehicle_type_name).first()
        
        if existing_type:
            vehicle.vehicle_type = existing_type
            vehicle.save(update_fields=["vehicle_type"])
            return True

        # Create new vehicle type
        new_type = VehicleType.objects.create(
            name=vehicle_type_name,
            style=vehicle_type_data.get("style", ""),
            fuel=vehicle_type_data.get("fuel", ""),
            company=vehicle_type_data.get("company", ""),
        )
        vehicle.vehicle_type = new_type
        vehicle.save(update_fields=["vehicle_type"])
        logger.info("Created new vehicle type: %s", vehicle_type_name)
        return True
