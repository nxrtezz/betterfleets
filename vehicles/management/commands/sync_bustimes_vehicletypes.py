from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from vehicles.models import FuelType, VehicleType, VehicleTypeType


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


class Command(BaseCommand):
    help = "Sync all vehicle types from the Bustimes API"

    protected_fields = {"name", "style", "fuel", "company"}

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--since", help="Incremental watermark where supported by the API")
        parser.add_argument("--limit", type=int, help="Maximum items per paginated API request")

    def handle(self, *args, **options):
        base_url = settings.BUSTIMES_API_BASE_URL.strip()
        if not base_url:
            raise CommandError("BUSTIMES_API_BASE_URL is not configured")

        token = settings.BUSTIMES_API_TOKEN.strip()
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.options = options
        self.stats = SyncStats()

        with transaction.atomic():
            self.sync_vehicle_types()

            if options["dry_run"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))

        self.stdout.write(
            "vehicletypes: "
            f"created={self.stats.created} "
            f"updated={self.stats.updated} "
            f"skipped={self.stats.skipped} "
            f"errors={self.stats.errors}"
        )

    def _request_params(self):
        params = {}
        if self.options.get("since"):
            params["since"] = self.options["since"]
        if self.options.get("limit"):
            params["limit"] = self.options["limit"]
        return params

    def _fetch_collection(self, endpoint: str):
        params = self._request_params()
        next_url = urljoin(self.base_url, endpoint.lstrip("/"))

        while next_url:
            response = self.session.get(next_url, params=params or None, timeout=20)
            params = None
            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, list):
                items = payload
                next_url = None
            else:
                items = payload.get("results") or payload.get("items") or payload.get("data") or []
                next_url = payload.get("next")

            for item in items:
                yield item

    @staticmethod
    def _first(*values):
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _extract_external_id(self, item):
        value = self._first(item.get("external_id"), item.get("id"))
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _parse_bool(value):
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _coerce_style(self, item):
        allowed = {choice for choice, _label in VehicleTypeType.choices}
        style = str(item.get("style") or "").strip().lower()
        if style in allowed:
            return style

        double_decker = self._parse_bool(item.get("double_decker"))
        coach = self._parse_bool(item.get("coach"))

        if double_decker and coach:
            return VehicleTypeType.DOUBLE_DECK_COACH
        if coach:
            return VehicleTypeType.COACH
        if double_decker:
            return VehicleTypeType.DOUBLE_DECKER
        return VehicleTypeType.SINGLE_DECKER

    def _coerce_fuel(self, item):
        allowed = {choice for choice, _label in FuelType.choices}
        fuel = str(item.get("fuel") or "").strip().lower()
        if fuel in allowed:
            return fuel

        for key, mapped in (
            ("electric", FuelType.ELECTRIC),
            ("hybrid", FuelType.HYBRID),
            ("hydrogen", FuelType.HYDROGEN),
            ("gas", FuelType.GAS),
        ):
            if self._parse_bool(item.get(key)):
                return mapped

        return FuelType.DIESEL if fuel else ""

    def _apply_updates(self, instance, updates):
        dirty = []
        for field, value in updates.items():
            if getattr(instance, "is_manual", False) and field in self.protected_fields:
                continue
            if getattr(instance, field) != value:
                setattr(instance, field, value)
                dirty.append(field)
        return dirty

    def sync_vehicle_types(self):
        for item in self._fetch_collection("/api/vehicletypes/"):
            try:
                external_id = self._extract_external_id(item)
                name = (item.get("name") or "").strip()
                if not name:
                    self.stats.errors += 1
                    continue

                vehicle_type = None
                if external_id:
                    vehicle_type = VehicleType.objects.filter(external_id=external_id).first()
                if not vehicle_type:
                    vehicle_type = VehicleType.objects.filter(name__iexact=name).first()

                values = {
                    "name": name,
                    "style": self._coerce_style(item),
                    "fuel": self._coerce_fuel(item),
                    "company": item.get("company") or "",
                    "external_id": external_id,
                }

                if not vehicle_type:
                    VehicleType.objects.create(**values)
                    self.stats.created += 1
                    continue

                dirty = self._apply_updates(vehicle_type, values)
                if dirty:
                    vehicle_type.save(update_fields=dirty)
                    self.stats.updated += 1
                else:
                    self.stats.skipped += 1
            except Exception:
                self.stats.errors += 1
