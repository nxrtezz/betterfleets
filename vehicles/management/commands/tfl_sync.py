from datetime import timedelta
import logging

import requests
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from busstops.bustimes_sync import BustimesApiClient
from busstops.models import Operator
from vehicles.models import Livery, Vehicle, VehicleType, VehicleFeature
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

        # Collect all updates
        update_fields = []

        # Sync operator
        if bustimes_vehicle.get("operator") and bustimes_vehicle["operator"].get("id"):
            operator_noc = bustimes_vehicle["operator"]["id"]
            if vehicle.operator and vehicle.operator.noc != operator_noc:
                new_operator = Operator.objects.filter(noc=operator_noc).first()
                if new_operator:
                    vehicle.operator = new_operator
                    update_fields.append("operator")
                    logger.info("Will update operator to %s for vehicle %s", operator_noc, vehicle.reg)
                    updated = True

        # Sync livery using name and CSS
        if bustimes_vehicle.get("livery"):
            livery_name = bustimes_vehicle["livery"].get("name")
            if livery_name:
                existing_livery = Livery.objects.filter(name=livery_name).first()
                if existing_livery:
                    if not vehicle.livery or vehicle.livery.name != livery_name:
                        vehicle.livery = existing_livery
                        update_fields.append("livery")
                        updated = True
                else:
                    left_css = bustimes_vehicle["livery"].get("left", "")
                    right_css = bustimes_vehicle["livery"].get("right", "")
                    new_livery = Livery.objects.create(
                        name=livery_name,
                        left_css=left_css,
                        right_css=right_css,
                        published=True,
                    )
                    vehicle.livery = new_livery
                    update_fields.append("livery")
                    logger.info("Created new livery: %s", livery_name)
                    updated = True

        # Sync vehicle type using name
        if bustimes_vehicle.get("vehicle_type"):
            vehicle_type_name = bustimes_vehicle["vehicle_type"].get("name")
            if vehicle_type_name:
                existing_type = VehicleType.objects.filter(name=vehicle_type_name).first()
                if existing_type:
                    if not vehicle.vehicle_type or vehicle.vehicle_type.name != vehicle_type_name:
                        vehicle.vehicle_type = existing_type
                        update_fields.append("vehicle_type")
                        updated = True
                else:
                    new_type = VehicleType.objects.create(
                        name=vehicle_type_name,
                        style=bustimes_vehicle["vehicle_type"].get("style", ""),
                        fuel=bustimes_vehicle["vehicle_type"].get("fuel", ""),
                        company=bustimes_vehicle["vehicle_type"].get("company", ""),
                        manufacturer=bustimes_vehicle["vehicle_type"].get("manufacturer", ""),
                        group=bustimes_vehicle["vehicle_type"].get("group", ""),
                    )
                    vehicle.vehicle_type = new_type
                    update_fields.append("vehicle_type")
                    logger.info("Created new vehicle type: %s", vehicle_type_name)
                    updated = True

        # Sync branding
        if bustimes_vehicle.get("branding"):
            branding = bustimes_vehicle["branding"]
            if vehicle.branding != branding:
                vehicle.branding = branding
                update_fields.append("branding")
                updated = True

        # Sync fleet code
        if bustimes_vehicle.get("fleet_code"):
            fleet_code = bustimes_vehicle["fleet_code"]
            if vehicle.fleet_code != fleet_code:
                vehicle.fleet_code = fleet_code
                update_fields.append("fleet_code")
                updated = True

        # Save all field updates at once
        if update_fields:
            vehicle.save(update_fields=update_fields)

        # Sync special features (separate M2M operation)
        if bustimes_vehicle.get("special_features"):
            for feature_name in bustimes_vehicle["special_features"]:
                feature, created = VehicleFeature.objects.get_or_create(name=feature_name)
                if feature not in vehicle.features.all():
                    vehicle.features.add(feature)
                    logger.info("Added feature %s to vehicle %s", feature_name, vehicle.reg)
                    updated = True

        if updated:
            self.stdout.write(f"Updated vehicle {vehicle.code} ({vehicle.reg})")
            return "updated"

        return "no_change"
