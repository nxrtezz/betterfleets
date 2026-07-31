from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.models.signals import post_save

from vehicles.models import Livery, Vehicle
from vehicles.signals import liveries_cache_update

from .sync_bustimes_fleet import Command as SyncFleetCommand


@dataclass
class RepairStats:
    total_scanned: int = 0
    colours_fixed: int = 0
    inferred_fixed: int = 0
    api_fixed: int = 0
    unresolved: int = 0

    @property
    def fixed_entries(self) -> int:
        return self.colours_fixed + self.inferred_fixed + self.api_fixed


class Command(SyncFleetCommand):
    help = (
        "Repair missing vehicle liveries using local patterns first, "
        "with optional Bustimes fleet API fallback"
    )
    protected_livery_fields = {
        "name",
        "colour",
        "colours",
        "left_css",
        "right_css",
        "published",
        "show_name",
        "white_text",
        "text_colour",
        "stroke_colour",
    }
    default_colour = "#808080"
    hex_re = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--operator", help="Filter vehicles by operator noc or slug")
        parser.add_argument("--since", help="Incremental watermark where supported by API")
        parser.add_argument("--limit", type=int, help="Maximum items per endpoint request")
        parser.add_argument(
            "--progress-every",
            type=int,
            default=250,
            help="Print progress every N vehicles processed",
        )

    def handle(self, *args, **options):
        self.options = options
        self.stats = RepairStats()
        self.synced_liveries = {}
        self.unresolved_vehicle_ids = []
        self._build_pattern_indexes()
        self.stats.total_scanned = self._candidate_queryset().count()
        self.progress_every = max(int(options.get("progress_every") or 250), 1)

        if self.stats.total_scanned:
            self.stdout.write(
                f"Starting livery repair for {self.stats.total_scanned} vehicle(s)"
            )

        post_save.disconnect(liveries_cache_update, sender=Livery)
        try:
            if options["dry_run"]:
                with transaction.atomic():
                    self.repair_from_patterns()
                    self.repair_from_api_if_configured()
                    self._finalize_stats()
                    self._write_summary(dry_run=True)
                    transaction.set_rollback(True)
                return

            self.repair_from_patterns()
            self.repair_from_api_if_configured()
            self._finalize_stats()
            self._write_summary(dry_run=False)
        finally:
            post_save.connect(liveries_cache_update, sender=Livery)

    def _verbosity(self):
        return int(self.options.get("verbosity", 1))

    def _log_verbose(self, message, level=2):
        if self._verbosity() >= level:
            self.stdout.write(message)

    def _describe_vehicle(self, vehicle):
        parts = [f"vehicle id={vehicle.pk}"]
        if vehicle.operator_id:
            parts.append(f"operator={vehicle.operator_id}")
        if vehicle.code:
            parts.append(f"code={vehicle.code}")
        if vehicle.reg:
            parts.append(f"reg={vehicle.reg}")
        return " ".join(parts)

    def _write_progress(self, stage, processed, total, extra=""):
        if total:
            percentage = processed / total * 100
            message = f"{stage}: {processed}/{total} ({percentage:.1f}%)"
        else:
            message = f"{stage}: {processed}"
        if extra:
            message = f"{message} {extra}"
        self.stdout.write(message)

    def _maybe_write_progress(self, stage, processed, total, extra=""):
        if processed == 1 or processed % self.progress_every == 0 or processed == total:
            self._write_progress(stage, processed, total, extra=extra)

    def _apply_operator_filter(self, queryset):
        operator_filter = self.options.get("operator")
        if not operator_filter:
            return queryset
        return queryset.filter(
            Q(operator__noc__iexact=operator_filter)
            | Q(operator__slug__iexact=operator_filter)
        )

    def _candidate_queryset(self):
        queryset = Vehicle.objects.filter(livery__isnull=True).select_related(
            "operator", "vehicle_type"
        )
        return self._apply_operator_filter(queryset).order_by("id")

    def _reference_queryset(self):
        queryset = Vehicle.objects.filter(livery__isnull=False)
        return self._apply_operator_filter(queryset)

    def _build_pattern_indexes(self):
        queryset = self._reference_queryset()

        self.operator_liveries = {
            row["operator_id"]: row["livery_id"]
            for row in queryset.filter(operator__isnull=False)
            .values("operator_id")
            .annotate(distinct_liveries=Count("livery_id", distinct=True), livery_id=Max("livery_id"))
            .filter(distinct_liveries=1)
        }

        self.operator_type_liveries = {
            (row["operator_id"], row["vehicle_type_id"]): row["livery_id"]
            for row in queryset.filter(operator__isnull=False, vehicle_type__isnull=False)
            .values("operator_id", "vehicle_type_id")
            .annotate(distinct_liveries=Count("livery_id", distinct=True), livery_id=Max("livery_id"))
            .filter(distinct_liveries=1)
        }

        self.operator_style_liveries = {
            (row["operator_id"], row["vehicle_type__style"]): row["livery_id"]
            for row in queryset.filter(
                operator__isnull=False,
                vehicle_type__isnull=False,
            )
            .exclude(vehicle_type__style="")
            .values("operator_id", "vehicle_type__style")
            .annotate(distinct_liveries=Count("livery_id", distinct=True), livery_id=Max("livery_id"))
            .filter(distinct_liveries=1)
        }

        self.operator_colours_liveries = {
            (row["operator_id"], row["colours"]): row["livery_id"]
            for row in queryset.filter(operator__isnull=False)
            .exclude(colours="")
            .exclude(colours="Other")
            .values("operator_id", "colours")
            .annotate(distinct_liveries=Count("livery_id", distinct=True), livery_id=Max("livery_id"))
            .filter(distinct_liveries=1)
        }

    def _resolve_livery_from_colours(self, vehicle):
        if not vehicle.colours or vehicle.colours == "Other":
            return None

        matches = list(Livery.objects.filter(colours__iexact=vehicle.colours)[:2])
        if len(matches) == 1:
            return matches[0]

        if " " not in vehicle.colours:
            matches = list(Livery.objects.filter(colour__iexact=vehicle.colours)[:2])
            if len(matches) == 1:
                return matches[0]

        return None

    def _resolve_livery_from_patterns(self, vehicle):
        if vehicle.operator_id and vehicle.vehicle_type_id:
            livery_id = self.operator_type_liveries.get(
                (vehicle.operator_id, vehicle.vehicle_type_id)
            )
            if livery_id:
                return Livery.objects.filter(pk=livery_id).first()

        if vehicle.operator_id and vehicle.colours and vehicle.colours != "Other":
            livery_id = self.operator_colours_liveries.get(
                (vehicle.operator_id, vehicle.colours)
            )
            if livery_id:
                return Livery.objects.filter(pk=livery_id).first()

        if vehicle.operator_id and vehicle.vehicle_type and vehicle.vehicle_type.style:
            livery_id = self.operator_style_liveries.get(
                (vehicle.operator_id, vehicle.vehicle_type.style)
            )
            if livery_id:
                return Livery.objects.filter(pk=livery_id).first()

        if vehicle.operator_id:
            livery_id = self.operator_liveries.get(vehicle.operator_id)
            if livery_id:
                return Livery.objects.filter(pk=livery_id).first()

        return None

    def repair_from_patterns(self):
        candidates = list(self._candidate_queryset())
        total = len(candidates)
        if total:
            self.stdout.write("Pattern pass: checking local matches")

        for index, vehicle in enumerate(candidates, start=1):
            livery = self._resolve_livery_from_colours(vehicle)
            if livery:
                vehicle.livery = livery
                vehicle.save(update_fields=["livery"])
                self.stats.colours_fixed += 1
                self._log_verbose(
                    f"pattern colours: assigned livery '{livery.name}' to {self._describe_vehicle(vehicle)}"
                )
                self._maybe_write_progress(
                    "pattern pass",
                    index,
                    total,
                    extra=(
                        f"fixed={self.stats.colours_fixed + self.stats.inferred_fixed}"
                    ),
                )
                continue

            livery = self._resolve_livery_from_patterns(vehicle)
            if livery:
                vehicle.livery = livery
                vehicle.save(update_fields=["livery"])
                self.stats.inferred_fixed += 1
                self._log_verbose(
                    f"pattern inferred: assigned livery '{livery.name}' to {self._describe_vehicle(vehicle)}"
                )

            self._maybe_write_progress(
                "pattern pass",
                index,
                total,
                extra=f"fixed={self.stats.colours_fixed + self.stats.inferred_fixed}",
            )

    def repair_from_api_if_configured(self):
        base_url = settings.BUSTIMES_API_BASE_URL.strip()
        if not base_url:
            return

        token = settings.BUSTIMES_API_TOKEN.strip()
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.repair_from_api()

    def _request_params(self, endpoint=None):
        params = {}
        if self.options.get("since"):
            params["since"] = self.options["since"]
        if self.options.get("limit"):
            params["limit"] = self.options["limit"]
        return params

    def _resolve_api_livery_name(self, item, livery_value):
        if isinstance(livery_value, dict):
            name = (livery_value.get("name") or "").strip()
            if name:
                return name

        for key in ("livery_name", "livery_label", "livery_display_name"):
            name = str(item.get(key) or "").strip()
            if name:
                return name

        if isinstance(livery_value, str):
            stripped = livery_value.strip()
            if stripped and not stripped.isdigit():
                return stripped

        return None

    def _extract_api_livery_id(self, value):
        if value in (None, ""):
            return None
        if isinstance(value, dict):
            value = self._first(value.get("external_id"), value.get("id"))
        if value in (None, ""):
            return None
        return str(value).strip() or None

    def _extract_livery_colour(self, *values):
        for value in values:
            if not value:
                continue
            match = self.hex_re.search(str(value))
            if not match:
                continue
            colour = match.group(0).lower()
            if len(colour) == 4:
                return "#" + "".join(char * 2 for char in colour[1:])
            if len(colour) >= 7:
                return colour[:7]
        return self.default_colour

    def _apply_livery_updates(self, livery, values):
        dirty = []
        for field, value in values.items():
            if livery.is_manual and field in self.protected_livery_fields:
                continue
            if getattr(livery, field) != value:
                setattr(livery, field, value)
                dirty.append(field)
        return dirty

    def _fetch_api_livery_record(self, livery_id):
        response = self.session.get(
            urljoin(self.base_url, "api/liveries/"),
            params={"id": livery_id, **self._request_params()},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            items = payload
        else:
            items = payload.get("results") or payload.get("items") or payload.get("data") or []
        return items[0] if items else None

    def _sync_exact_api_livery(self, livery_id):
        cache_key = str(livery_id or "").strip()
        if not cache_key:
            return None
        if cache_key in self.synced_liveries:
            return self.synced_liveries[cache_key]

        item = self._fetch_api_livery_record(cache_key)
        if not item:
            self.synced_liveries[cache_key] = None
            return None

        external_id = self._first(item.get("external_id"), item.get("id"))
        if external_id not in (None, ""):
            external_id = str(external_id)
        name = (item.get("name") or "").strip()
        if not name:
            self.synced_liveries[cache_key] = None
            return None

        left_css = item.get("left") or item.get("left_css") or ""
        right_css = item.get("right") or item.get("right_css") or left_css
        values = {
            "external_id": external_id,
            "name": name,
            "colour": self._extract_livery_colour(
                item.get("colour"),
                item.get("stroke_colour"),
                item.get("text_colour"),
                left_css,
                right_css,
            ),
            "left_css": left_css,
            "right_css": right_css,
            "white_text": bool(item.get("white_text")),
            "text_colour": (item.get("text_colour") or "").strip(),
            "stroke_colour": (item.get("stroke_colour") or "").strip(),
            "published": True,
            "show_name": True,
        }

        livery = None
        if external_id:
            livery = Livery.objects.filter(external_id=external_id).first()
        if not livery:
            livery = Livery.objects.filter(name__iexact=name).first()

        if not livery:
            livery = Livery.objects.create(**values)
            self._log_verbose(
                f"api livery: created local livery '{livery.name}' (external_id={external_id})"
            )
        else:
            dirty = self._apply_livery_updates(livery, values)
            if dirty:
                livery.save(update_fields=dirty)
                self._log_verbose(
                    f"api livery: updated local livery '{livery.name}' fields={','.join(dirty)}"
                )
            else:
                self._log_verbose(
                    f"api livery: reused local livery '{livery.name}' (external_id={external_id})",
                    level=3,
                )

        self.synced_liveries[cache_key] = livery
        return livery

    def _resolve_livery_from_api_payload(self, item):
        livery_value = self._first(item.get("livery"), item.get("livery_id"))
        livery_name = self._resolve_api_livery_name(item, livery_value)
        if livery_name:
            livery = Livery.objects.filter(name__iexact=livery_name).first()
            if livery:
                return livery

        livery_id = self._extract_api_livery_id(livery_value)
        if livery_id:
            return self._sync_exact_api_livery(livery_id)

        return self._resolve_livery(livery_value)

    def repair_from_api(self):
        candidates = list(self._candidate_queryset())
        total = len(candidates)
        if not total:
            return

        self.stdout.write(f"API pass: checking Bustimes for {total} unresolved vehicle(s)")

        by_external_id = {
            str(vehicle.external_id): vehicle
            for vehicle in candidates
            if vehicle.external_id
        }
        by_code = {
            (vehicle.operator_id, vehicle.code.upper()): vehicle
            for vehicle in candidates
            if vehicle.operator_id and vehicle.code
        }
        by_reg = {
            (vehicle.operator_id, vehicle.reg.upper()): vehicle
            for vehicle in candidates
            if vehicle.operator_id and vehicle.reg
        }
        matched_candidate_ids = set()

        for item in self._fetch_collection("/api/vehicles/"):
            operator = self._resolve_operator(
                self._first(item.get("operator"), item.get("operator_id"), item.get("noc"))
            )
            if not operator:
                continue

            external_id = self._extract_external_id(item, "id")
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

            vehicle = None
            if external_id:
                vehicle = by_external_id.get(str(external_id))
            if not vehicle and code:
                vehicle = by_code.get((operator.pk, str(code).upper()))
            if not vehicle and reg:
                vehicle = by_reg.get((operator.pk, reg.upper()))
            if not vehicle or vehicle.livery_id:
                continue

            matched_candidate_ids.add(vehicle.pk)
            livery = self._resolve_livery_from_api_payload(item)
            if livery:
                vehicle.livery = livery
                vehicle.save(update_fields=["livery"])
                self.stats.api_fixed += 1
                self._log_verbose(
                    f"api assign: assigned livery '{livery.name}' to {self._describe_vehicle(vehicle)}"
                )
            else:
                self._log_verbose(
                    f"api unresolved: no Bustimes livery match for {self._describe_vehicle(vehicle)}"
                )

            self._maybe_write_progress(
                "api pass",
                len(matched_candidate_ids),
                total,
                extra=f"api_fixed={self.stats.api_fixed}",
            )

        unmatched = total - len(matched_candidate_ids)
        if unmatched:
            self.stdout.write(
                self.style.WARNING(
                    f"API pass: {unmatched} vehicle(s) were not matched to a Bustimes vehicle record"
                )
            )

    def _finalize_stats(self):
        unresolved = list(self._candidate_queryset().values_list("pk", flat=True))
        self.unresolved_vehicle_ids = unresolved
        self.stats.unresolved = len(unresolved)

    def _write_summary(self, dry_run=False):
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))

        self.stdout.write(
            "vehicle liveries: "
            f"scanned={self.stats.total_scanned} "
            f"fixed={self.stats.fixed_entries} "
            f"colours_fixed={self.stats.colours_fixed} "
            f"inferred_fixed={self.stats.inferred_fixed} "
            f"api_fixed={self.stats.api_fixed} "
            f"unresolved={self.stats.unresolved}"
        )

        verbosity = self._verbosity()
        if self.unresolved_vehicle_ids and verbosity >= 2:
            for vehicle_id in self.unresolved_vehicle_ids:
                self.stdout.write(self.style.WARNING(f"unresolved vehicle id={vehicle_id}"))
