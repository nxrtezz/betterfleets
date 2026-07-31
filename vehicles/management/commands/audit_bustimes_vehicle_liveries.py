from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from tqdm import tqdm

from busstops.models import Operator
from vehicles.models import Livery, Vehicle


HEX_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?")
DEFAULT_COLOUR = "#808080"


@dataclass
class AuditStats:
    scanned: int = 0
    matched_bustimes: int = 0
    unmatched_bustimes: int = 0
    manual_skipped: int = 0
    no_bustimes_livery: int = 0
    already_ok: int = 0
    livery_created: int = 0
    livery_updated: int = 0
    vehicle_reassigned: int = 0
    errors: int = 0


class Command(BaseCommand):
    help = (
        "Audit all vehicles against the Bustimes fleet API livery CSS/name. "
        "If a mismatch is found, update/reassign to the Bustimes livery unless the vehicle or livery is manual."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            help="Filter vehicles by operator noc/id or slug (also limits Bustimes API scan where supported)",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--only-mismatches",
            action="store_true",
            help="Only output details for vehicles that mismatch Bustimes livery",
        )
        parser.add_argument(
            "--progress",
            action="store_true",
            help="Force a progress bar even when verbosity is low",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum items per paginated API request (passed through to Bustimes API if supported)",
        )
        parser.add_argument(
            "--since",
            help="Incremental watermark for Bustimes API where supported (usually not appropriate for a full audit)",
        )

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
        self.stats = AuditStats()

        operator_filter = (options.get("operator") or "").strip()
        operator_obj = self._resolve_operator_filter(operator_filter) if operator_filter else None

        vehicle_qs = (
            Vehicle.objects.select_related("operator", "livery")
            .order_by("id")
        )
        if operator_obj:
            vehicle_qs = vehicle_qs.filter(operator=operator_obj)
        elif operator_filter:
            vehicle_qs = vehicle_qs.filter(
                Q(operator__noc__iexact=operator_filter)
                | Q(operator__slug__iexact=operator_filter)
                | Q(operator__pk__iexact=operator_filter)
            )

        total = vehicle_qs.count()
        if not total:
            self.stdout.write("No vehicles matched the filter.")
            return

        self.stdout.write(f"Scanning Bustimes vehicle feed to build match indexes…")
        bustimes_index = self._build_bustimes_vehicle_index(operator_filter=operator_filter)
        self.stdout.write(
            f"Bustimes index: external_id={len(bustimes_index['by_external_id'])} "
            f"code={len(bustimes_index['by_code'])} reg={len(bustimes_index['by_reg'])}"
        )

        use_progress = bool(options.get("progress")) or int(options.get("verbosity", 1)) >= 1
        iterator = vehicle_qs.iterator(chunk_size=2000)
        if use_progress:
            iterator = tqdm(iterator, total=total, unit="vehicle")

        if options["dry_run"]:
            with transaction.atomic():
                self._audit_vehicles(iterator, bustimes_index, total=total)
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))
        else:
            self._audit_vehicles(iterator, bustimes_index, total=total)

        self.stdout.write(
            "audit: "
            f"scanned={self.stats.scanned} "
            f"matched={self.stats.matched_bustimes} "
            f"unmatched={self.stats.unmatched_bustimes} "
            f"manual_skipped={self.stats.manual_skipped} "
            f"no_bustimes_livery={self.stats.no_bustimes_livery} "
            f"already_ok={self.stats.already_ok} "
            f"livery_created={self.stats.livery_created} "
            f"livery_updated={self.stats.livery_updated} "
            f"vehicle_reassigned={self.stats.vehicle_reassigned} "
            f"errors={self.stats.errors}"
        )

    def _resolve_operator_filter(self, value: str) -> Operator | None:
        if not value:
            return None
        return Operator.objects.filter(
            Q(noc__iexact=value) | Q(slug__iexact=value) | Q(pk__iexact=value)
        ).first()

    def _request_params(self, endpoint: str, operator_filter: str):
        params = {}
        if endpoint == "/api/vehicles/" and operator_filter:
            params["operator"] = operator_filter
        if self.options.get("since"):
            params["since"] = self.options["since"]
        if self.options.get("limit"):
            params["limit"] = self.options["limit"]
        return params

    def _fetch_collection(self, endpoint: str, operator_filter: str):
        params = self._request_params(endpoint, operator_filter)
        next_url = urljoin(self.base_url, endpoint.lstrip("/"))

        while next_url:
            response = self.session.get(next_url, params=params or None, timeout=30)
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

    @staticmethod
    def _normalize_reg(value):
        if not value:
            return ""
        return str(value).upper().replace(" ", "")

    @staticmethod
    def _normalize_css(value: str | None) -> str:
        return (value or "").strip()

    def _extract_colour(self, *values):
        for value in values:
            if not value:
                continue
            match = HEX_RE.search(str(value))
            if not match:
                continue
            colour = match.group(0).lower()
            if len(colour) == 4:
                return "#" + "".join(char * 2 for char in colour[1:])
            if len(colour) >= 7:
                return colour[:7]
        return DEFAULT_COLOUR

    def _build_bustimes_vehicle_index(self, operator_filter: str):
        by_external_id: dict[str, dict] = {}
        by_code: dict[tuple[str, str], dict] = {}
        by_reg: dict[tuple[str, str], dict] = {}

        for item in self._fetch_collection("/api/vehicles/", operator_filter=operator_filter):
            operator = self._first(
                (item.get("operator") or {}).get("id") if isinstance(item.get("operator"), dict) else None,
                item.get("operator_id"),
                item.get("noc"),
                (item.get("operator") or {}).get("noc") if isinstance(item.get("operator"), dict) else None,
                (item.get("operator") or {}).get("slug") if isinstance(item.get("operator"), dict) else None,
            )
            if not operator:
                continue
            operator = str(operator)

            external_id = self._first(item.get("external_id"), item.get("id"))
            if external_id not in (None, ""):
                by_external_id[str(external_id)] = item

            code = self._first(item.get("code"), item.get("fleet_code"), item.get("fleet_number"))
            if code not in (None, ""):
                by_code[(operator, str(code).upper())] = item

            reg = self._normalize_reg(self._first(item.get("reg"), item.get("registration")))
            if reg:
                by_reg[(operator, reg.upper())] = item

        return {"by_external_id": by_external_id, "by_code": by_code, "by_reg": by_reg}

    def _match_bustimes_vehicle(self, vehicle: Vehicle, index: dict):
        if vehicle.external_id:
            item = index["by_external_id"].get(str(vehicle.external_id))
            if item:
                return item

        if vehicle.operator_id and vehicle.code:
            item = index["by_code"].get((str(vehicle.operator_id), str(vehicle.code).upper()))
            if item:
                return item

        if vehicle.operator_id and vehicle.reg:
            item = index["by_reg"].get((str(vehicle.operator_id), str(vehicle.reg).upper()))
            if item:
                return item

        return None

    def _audit_vehicles(self, iterator, index: dict, total: int):
        verbose = int(self.options.get("verbosity", 1))
        only_mismatches = bool(self.options.get("only_mismatches"))

        for vehicle in iterator:
            self.stats.scanned += 1
            try:
                item = self._match_bustimes_vehicle(vehicle, index)
                if not item:
                    self.stats.unmatched_bustimes += 1
                    continue

                self.stats.matched_bustimes += 1

                api_livery = item.get("livery") or {}
                if not isinstance(api_livery, dict) or not api_livery:
                    self.stats.no_bustimes_livery += 1
                    continue

                api_livery_id = self._first(api_livery.get("external_id"), api_livery.get("id"))
                api_name = (api_livery.get("name") or "").strip()
                api_left = self._normalize_css(self._first(api_livery.get("left"), api_livery.get("left_css")))
                api_right = self._normalize_css(
                    self._first(api_livery.get("right"), api_livery.get("right_css"), api_left)
                )

                current = vehicle.livery
                current_name = (getattr(current, "name", "") or "").strip()
                current_left = self._normalize_css(getattr(current, "left_css", ""))
                current_right = self._normalize_css(getattr(current, "right_css", "") or current_left)

                mismatch = (
                    (api_name and api_name != current_name)
                    or api_left != current_left
                    or api_right != current_right
                )
                if not mismatch:
                    self.stats.already_ok += 1
                    continue

                if only_mismatches and verbose >= 2:
                    self.stdout.write(
                        f"mismatch vehicle id={vehicle.pk} operator={vehicle.operator_id or '?'} "
                        f"code={vehicle.code!r} bustimes_livery={api_livery_id} {api_name!r}"
                    )

                if vehicle.is_manual or (current and current.is_manual):
                    self.stats.manual_skipped += 1
                    continue

                if api_livery_id in (None, "") or not api_name:
                    self.stats.no_bustimes_livery += 1
                    continue

                external_id = str(api_livery_id)
                target = Livery.objects.filter(external_id=external_id).first()
                creating = target is None
                if not target:
                    target = Livery(external_id=external_id)

                desired = {
                    "name": api_name,
                    "left_css": api_left,
                    "right_css": api_right,
                    "colour": self._extract_colour(api_left, api_right),
                    "published": True,
                    "show_name": True,
                }

                dirty = []
                if not getattr(target, "is_manual", False):
                    for field, value in desired.items():
                        if getattr(target, field) != value:
                            setattr(target, field, value)
                            dirty.append(field)

                if creating:
                    target.save()
                    self.stats.livery_created += 1
                elif dirty:
                    target.save(update_fields=dirty)
                    self.stats.livery_updated += 1

                if vehicle.livery_id != target.pk:
                    vehicle.livery = target
                    vehicle.save(update_fields=["livery"])
                    self.stats.vehicle_reassigned += 1

            except Exception as exc:
                self.stats.errors += 1
                if verbose >= 2:
                    self.stdout.write(self.style.WARNING(f"error vehicle id={vehicle.pk}: {exc}"))

