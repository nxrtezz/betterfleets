from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from busstops.models import DataSource, Operator, Region
from bustimes.models import Garage
from vehicles.models import Livery, Vehicle, VehicleType


@dataclass
class ModelStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


class Command(BaseCommand):
    help = "Sync fleet entities from a Bustimes API into local operator/fleet models"

    protected_fields = {
        "operator": {
            "name",
            "slug",
            "aka",
            "slogan",
            "url",
            "social_x",
            "social_fb",
            "social_other",
            "vehicle_mode",
            "region",
        },
        "vehicle_type": {"name", "style", "fuel", "company"},
        "livery": {"name", "colour", "left_css", "right_css", "colours"},
        "garage": {"code", "name", "operator", "region"},
        "vehicle": {
            "code",
            "fleet_number",
            "fleet_code",
            "reg",
            "prev_registration",
            "vehicle_type",
            "livery",
            "garage",
            "branding",
            "name",
            "notes",
            "withdrawn",
            "operator",
        },
    }

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--operator", help="Filter by operator id/noc where supported")
        parser.add_argument("--livery", help="Filter vehicles by Bustimes livery id/external_id")
        parser.add_argument("--skip-operators", action="store_true")
        parser.add_argument("--since", help="Incremental watermark where supported by API")
        parser.add_argument("--limit", type=int, help="Maximum items per endpoint request")

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
        self.stats = {
            "operators": ModelStats(),
            "vehicletypes": ModelStats(),
            "liveries": ModelStats(),
            "garages": ModelStats(),
            "vehicles": ModelStats(),
        }

        self.source, _ = DataSource.objects.get_or_create(
            name="Bustimes Fleet API",
            defaults={"url": self.base_url},
        )

        if options["dry_run"]:
            with transaction.atomic():
                if not options.get("skip_operators"):
                    self.sync_operators()
                self.sync_vehicles()
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))
        else:
            if not options.get("skip_operators"):
                self.sync_operators()
            self.sync_vehicles()

        for name, stats in self.stats.items():
            self.stdout.write(
                f"{name}: created={stats.created} updated={stats.updated} "
                f"skipped={stats.skipped} errors={stats.errors}"
            )

    def _request_params(self, endpoint: str):
        params = {}
        if endpoint == "/api/vehicles/" and self.options.get("operator"):
            params["operator"] = self.options["operator"]
        if endpoint == "/api/vehicles/" and self.options.get("livery"):
            params["livery"] = self.options["livery"]
        if self.options.get("since"):
            params["since"] = self.options["since"]
        if self.options.get("limit"):
            params["limit"] = self.options["limit"]
        return params

    def _fetch_collection(self, endpoint: str):
        params = self._request_params(endpoint)
        next_url = urljoin(self.base_url, endpoint.lstrip("/"))

        while next_url:
            response = self.session.get(next_url, params=params or None, timeout=20)
            params = None

            if response.status_code == 404:
                self.stdout.write(self.style.WARNING(f"Endpoint not found, skipping: {endpoint}"))
                return

            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, list):
                items = payload
                next_url = None
            elif isinstance(payload, dict):
                if "results" in payload:
                    items = payload["results"]
                    next_url = payload.get("next")
                else:
                    items = payload.get("data") or payload.get("items") or []
                    next_url = payload.get("next")
            else:
                items = []
                next_url = None

            for item in items:
                yield item

    @staticmethod
    def _first(*values):
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _extract_external_id(self, item: dict[str, Any], *keys: str) -> str | None:
        value = self._first(*(item.get(key) for key in keys), item.get("external_id"))
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _parse_bool(value):
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            return value
        value = str(value).strip().lower()
        if value in {"1", "true", "yes", "y", "on"}:
            return True
        if value in {"0", "false", "no", "n", "off"}:
            return False
        return None

    @staticmethod
    def _parse_int(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_reg(value):
        if not value:
            return ""
        return str(value).upper().replace(" ", "")

    def _resolve_operator(self, value):
        if isinstance(value, dict):
            value = self._first(value.get("id"), value.get("noc"), value.get("slug"))
        if value in (None, ""):
            return None
        return Operator.objects.filter(Q(pk=value) | Q(slug=value)).first()

    def _resolve_region(self, value):
        if isinstance(value, dict):
            value = self._first(value.get("id"), value.get("pk"), value.get("name"))
        if value in (None, ""):
            return None

        value = str(value)
        region = Region.objects.filter(pk=value).first()
        if region:
            return region

        return Region.objects.filter(name__iexact=value).first()

    def _resolve_vehicle_type(self, value):
        if isinstance(value, dict):
            name = value.get("name")
            value = self._first(name, value.get("external_id"), value.get("id"))
        if value in (None, ""):
            return None
        value = str(value)
        # Try to find by name first (text value from Bustimes)
        obj = VehicleType.objects.filter(name__iexact=value).first()
        if obj:
            return obj
        # Fall back to external_id
        obj = VehicleType.objects.filter(external_id=value).first()
        if obj:
            return obj
        # Fall back to ID
        if value.isdigit():
            obj = VehicleType.objects.filter(pk=int(value)).first()
            if obj:
                return obj
        return None

    def _resolve_livery(self, value):
        if isinstance(value, dict):
            name = value.get("name")
            value = self._first(name, value.get("external_id"), value.get("id"))
        if value in (None, ""):
            return None
        value = str(value)
        # Try to find by name first (text value from Bustimes)
        obj = Livery.objects.filter(name__iexact=value).first()
        if obj:
            return obj
        # Fall back to external_id
        obj = Livery.objects.filter(external_id=value).first()
        if obj:
            return obj
        # Fall back to ID
        if value.isdigit():
            obj = Livery.objects.filter(pk=int(value)).first()
            if obj:
                return obj
        return None

    def _resolve_garage(self, value, operator=None):
        if isinstance(value, dict):
            external_id = self._extract_external_id(value, "id")
            code = value.get("code") or ""
            garage = None
            if external_id:
                garage = Garage.objects.filter(external_id=external_id).first()
            if not garage and operator and code:
                garage = Garage.objects.filter(operator=operator, code__iexact=code).first()
            if not garage and code:
                garage = Garage.objects.filter(code__iexact=code).first()

            values = {
                "code": code,
                "name": value.get("name") or "",
                "operator": operator,
                "external_id": external_id,
            }
            if garage:
                dirty = self._apply_updates(garage, values, "garage")
                if dirty:
                    garage.save(update_fields=dirty)
                return garage
            if code or external_id:
                return Garage.objects.create(**values)
            return None

        if value in (None, ""):
            return None
        if str(value).isdigit():
            obj = Garage.objects.filter(pk=int(value)).first()
            if obj:
                return obj
        obj = Garage.objects.filter(external_id=str(value)).first()
        if obj:
            return obj
        return Garage.objects.filter(code__iexact=str(value)).first()

    def _apply_updates(self, instance, updates: dict[str, Any], protected_key: str):
        dirty = []
        for field, value in updates.items():
            if getattr(instance, "is_manual", False) and field in self.protected_fields[protected_key]:
                continue
            if getattr(instance, field) != value:
                setattr(instance, field, value)
                dirty.append(field)
        return dirty

    def _matches_vehicle_livery_filter(self, item: dict[str, Any]) -> bool:
        requested = self.options.get("livery")
        if not requested:
            return True

        value = self._first(item.get("livery"), item.get("livery_id"))
        if isinstance(value, dict):
            value = self._first(value.get("external_id"), value.get("id"), value.get("name"))
        if value in (None, ""):
            return False
        return str(value) == str(requested)

    def sync_operators(self):
        stats = self.stats["operators"]
        for item in self._fetch_collection("/api/operators/"):
            try:
                noc = self._first(item.get("noc"), item.get("id"))
                if not noc:
                    stats.errors += 1
                    continue

                noc = str(noc)
                external_id = self._extract_external_id(item, "external_id")

                operator = None
                if external_id:
                    operator = Operator.objects.filter(external_id=external_id).first()
                if not operator:
                    operator = Operator.objects.filter(pk=noc).first()

                if self.options.get("operator") and str(self.options["operator"]).upper() not in {
                    noc.upper(),
                    str(item.get("slug", "")).upper(),
                    str(item.get("name", "")).upper(),
                }:
                    continue

                values = {
                    "name": item.get("name") or noc,
                    "slug": item.get("slug") or (operator and operator.slug) or noc.lower(),
                    "aka": item.get("aka") or "",
                    "slogan": item.get("slogan") or "",
                    "url": item.get("url") or "",
                    "twitter": item.get("twitter") or "",
                    "social_x": item.get("social_x") or item.get("twitter") or "",
                    "social_fb": item.get("social_fb") or "",
                    "social_other": item.get("social_other") or "",
                    "vehicle_mode": self._first(item.get("mode"), item.get("vehicle_mode")) or "",
                    "external_id": external_id,
                    "source": self.source,
                }

                if "region_id" in item or "region" in item:
                    values["region"] = self._resolve_region(
                        self._first(item.get("region_id"), item.get("region"))
                    )

                if not operator:
                    operator = Operator(noc=noc)
                    for field, value in values.items():
                        setattr(operator, field, value)
                    operator.save()
                    stats.created += 1
                    continue

                dirty = self._apply_updates(operator, values, "operator")
                if dirty:
                    operator.save(update_fields=dirty)
                    stats.updated += 1
                else:
                    stats.skipped += 1
            except Exception:
                stats.errors += 1

    def sync_vehicles(self):
        stats = self.stats["vehicles"]
        for item in self._fetch_collection("/api/vehicles/"):
            try:
                if not self._matches_vehicle_livery_filter(item):
                    continue

                external_id = self._extract_external_id(item, "id")
                operator = self._resolve_operator(
                    self._first(item.get("operator"), item.get("operator_id"), item.get("noc"))
                )
                if not operator:
                    stats.errors += 1
                    continue

                fleet_number = self._parse_int(
                    self._first(item.get("fleet_num"), item.get("fleet_number"))
                )
                reg = self._normalize_reg(self._first(item.get("registration"), item.get("reg")))
                code = self._first(item.get("code"), item.get("fleet_code"))
                if not code:
                    if fleet_number is not None:
                        code = str(fleet_number)
                    elif reg:
                        code = reg

                if not code:
                    stats.errors += 1
                    continue

                vehicle = None
                if external_id:
                    vehicle = Vehicle.objects.filter(external_id=external_id).first()
                if not vehicle:
                    vehicle = operator.vehicle_set.filter(code__iexact=code).first()
                if not vehicle and reg:
                    vehicle = operator.vehicle_set.filter(reg__iexact=reg).first()

                values = {
                    "code": code,
                    "fleet_number": fleet_number,
                    "fleet_code": item.get("fleet_code") or "",
                    "reg": reg,
                    "prev_registration": self._normalize_reg(
                        self._first(item.get("prev_registration"), item.get("previous_reg"))
                    ),
                    "vehicle_type": self._resolve_vehicle_type(
                        self._first(item.get("vehicle_type"), item.get("vehicle_type_id"), item.get("vehicle_id"))
                    ),
                    "livery": self._resolve_livery(
                        self._first(item.get("livery"), item.get("livery_id"))
                    ),
                    "garage": self._resolve_garage(item.get("garage"), operator=operator),
                    "branding": item.get("branding") or "",
                    "name": item.get("name") or "",
                    "notes": item.get("notes") or "",
                    "withdrawn": bool(item.get("withdrawn", False)),
                    "operator": operator,
                    "external_id": external_id,
                    "source": self.source,
                }

                if not vehicle:
                    vehicle = Vehicle(**values)
                    vehicle.save()
                    stats.created += 1
                    continue

                dirty = self._apply_updates(vehicle, values, "vehicle")
                if dirty:
                    vehicle.save(update_fields=dirty)
                    stats.updated += 1
                else:
                    stats.skipped += 1
            except Exception:
                stats.errors += 1
