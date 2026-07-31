from __future__ import annotations

import hashlib
import re
from typing import Any

from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from django.db.models import Q
from django.utils.dateparse import parse_datetime

from busstops.bustimes_sync import BustimesApiClient, compact_registration, compact_text
from busstops.models import BustimesSyncState, DataSource, Operator, Region, Service, ServiceCode, StopPoint
from bustimes.models import Garage, Trip
from vehicles.models import Livery, Vehicle, VehicleCode, VehicleJourney, VehicleRevision, VehicleType


BUSTIMES_SCHEME = "bustimes"
BUSTIMES_SLUG_SCHEME = "bustimes-slug"
BUSTIMES_SOURCE_NAME = "Bustimes API"
HEX_COLOUR_RE = re.compile(r"#[0-9a-fA-F]{6}")


class ProgressBar:
    width = 28

    def __init__(self, command, *, enabled: bool):
        self.command = command
        self.enabled = enabled
        self.total = None
        self.done = 0
        self.created = 0
        self.updated = 0
        self.skipped = 0

    def start(self, *, total: int | None, url: str):
        self.total = total
        if self.enabled:
            self.command.stdout.write(f"Fetching {url}")
            self.render()

    def tick(self, *, created=0, updated=0, skipped=0):
        self.done += 1
        self.created += int(created)
        self.updated += int(updated)
        self.skipped += int(skipped)
        if self.enabled:
            self.render()

    def render(self):
        if self.total:
            ratio = min(self.done / self.total, 1)
            filled = int(self.width * ratio)
            bar = "#" * filled + "-" * (self.width - filled)
            percent = int(ratio * 100)
            total = str(self.total)
        else:
            bar = "." * self.width
            percent = 0
            total = "?"
        self.command.stdout.write(
            (
                f"\r[{bar}] {percent:3d}% {self.done}/{total} "
                f"created={self.created} updated={self.updated} skipped={self.skipped}"
            ),
            ending="",
        )

    def finish(self):
        if self.enabled:
            self.render()
            self.command.stdout.write("")


class BustimesSyncCommand(BaseCommand):
    endpoint = ""

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default=None)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--max-items", type=int)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--progress", action="store_true", help="Force progress output.")
        parser.add_argument("--no-progress", action="store_true", help="Disable progress output.")
        parser.add_argument("--timeout", type=int, default=30, help="Timeout in seconds for API requests (default: 30).")

    def get_client(self, options):
        base_url = options.get("base_url")
        timeout = options.get("timeout", 30)
        cache = getattr(self, "_client_cache", None)
        if cache is None:
            cache = {}
            self._client_cache = cache
        cache_key = f"{base_url}_{timeout}"
        if cache_key not in cache:
            cache[cache_key] = BustimesApiClient(base_url, timeout=timeout)
        return cache[cache_key]

    def get_query_params(self, options):
        return {}

    def show_progress(self, options):
        if options.get("no_progress"):
            return False
        if options.get("progress"):
            return True
        isatty = getattr(self.stdout, "isatty", None)
        return bool(isatty and isatty())

    def progress(self, options):
        return ProgressBar(self, enabled=self.show_progress(options))

    def iter_items(self, options):
        return self.get_client(options).iter_results(
            self.endpoint,
            limit=options["limit"],
            max_items=options.get("max_items"),
            params=self.get_query_params(options),
        )

    def iter_items_with_progress(self, options, progress):
        seen = 0
        started = False
        for payload, url in self.get_client(options).iter_pages(
            self.endpoint,
            limit=options["limit"],
            params=self.get_query_params(options),
        ):
            if not started:
                total = payload.get("count")
                if options.get("max_items") and total:
                    total = min(total, options["max_items"])
                progress.start(total=total, url=url)
                started = True
            for item in payload.get("results", []):
                if options.get("max_items") and seen >= options["max_items"]:
                    progress.finish()
                    return
                yield item
                seen += 1
        progress.finish()

    def get_source(self):
        source = getattr(self, "_source", None)
        if source is None:
            source, _ = DataSource.objects.get_or_create(
                name=BUSTIMES_SOURCE_NAME,
                defaults={"url": "https://bustimes.org/api/"},
            )
            self._source = source
        return source

    def print_summary(self, created, updated, skipped):
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {created}, updated {updated}, protected/skipped {skipped}"
            )
        )


def api_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("atco_code") or item.get("slug"))


def resolve_operator(value: Any) -> Operator | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("noc") or value.get("id") or value.get("code")
    value = compact_text(value)
    if not value:
        return None
    return (
        Operator.objects.filter(noc__iexact=value).first()
        or Operator.objects.filter(external_id=value).first()
        or Operator.objects.filter(operatorcode__code__iexact=value).first()
    )


def resolve_region(value: Any) -> Region | None:
    value = compact_text(value)
    if not value:
        return None
    return Region.objects.filter(pk=value).first()


def extract_livery_colour(*css_values: str) -> str:
    for css_value in css_values:
        match = HEX_COLOUR_RE.search(css_value or "")
        if match:
            return match.group(0).lower()
    return "#cccccc"


def anonymous_livery_name(left_css: str, right_css: str) -> str:
    digest = hashlib.md5(f"{left_css}|{right_css}".encode()).hexdigest()[:12]
    return f"Bustimes CSS {digest}"


def normalise_bustimes_livery(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        external_id = compact_text(value.get("id"))
        name = compact_text(value.get("name"))
        left_css = compact_text(
            value.get("left") or value.get("left_css") or value.get("css")
        )
        right_css = compact_text(
            value.get("right") or value.get("right_css") or left_css or value.get("css")
        )
        colour = compact_text(value.get("colour")) or extract_livery_colour(
            left_css, right_css
        )
        anonymous_css = bool(left_css and not external_id and not name)
        if anonymous_css:
            name = anonymous_livery_name(left_css, right_css)
    else:
        external_id = compact_text(value)
        name = compact_text(value)
        left_css = ""
        right_css = ""
        colour = ""
        anonymous_css = False

    return {
        "external_id": external_id,
        "name": name,
        "left_css": left_css,
        "right_css": right_css,
        "colour": colour,
        "anonymous_css": anonymous_css,
    }


def resolve_livery(value: Any) -> Livery | None:
    livery_data = normalise_bustimes_livery(value)
    external_id = livery_data["external_id"]
    name = livery_data["name"]
    left_css = livery_data["left_css"]
    right_css = livery_data["right_css"]

    if external_id:
        state = BustimesSyncState.objects.filter(
            object_type="livery", external_id=external_id, local_model="vehicles.livery"
        ).first()
        if state and state.local_pk:
            livery = Livery.objects.filter(pk=state.local_pk).first()
            if livery:
                return livery
    if left_css:
        css_values = [left_css]
        try:
            minified_left_css = Livery.minify(left_css)
        except Exception:
            minified_left_css = ""
        if minified_left_css and minified_left_css not in css_values:
            css_values.append(minified_left_css)

        right_css_values = [right_css] if right_css else []
        if right_css:
            try:
                minified_right_css = Livery.minify(right_css)
            except Exception:
                minified_right_css = ""
            if minified_right_css and minified_right_css not in right_css_values:
                right_css_values.append(minified_right_css)

        for css_value in css_values:
            liveries = Livery.objects.filter(left_css=css_value)
            if right_css_values:
                liveries = liveries.filter(right_css__in=right_css_values)
            if name:
                named_livery = liveries.filter(name__iexact=name).first()
                if named_livery:
                    return named_livery
            livery = liveries.first()
            if livery:
                return livery
    if name:
        livery = Livery.objects.filter(name__iexact=name).first()
        if livery:
            return livery
    if livery_data["anonymous_css"] and left_css:
        livery = Livery(
            name=name,
            show_name=False,
            colour=livery_data["colour"],
            left_css=left_css,
            right_css=right_css or left_css,
            published=True,
        )
        livery.save()
        return livery
    return None


def resolve_or_create_livery(value: Any, debug=False, skip_sync_state=False) -> Livery | None:
    livery_data = normalise_bustimes_livery(value)
    external_id = livery_data["external_id"]
    name = livery_data["name"]
    left_css = livery_data["left_css"]
    right_css = livery_data["right_css"]

    if debug:
        print(f"DEBUG resolve_or_create_livery: name={name}, external_id={external_id}, left_css={left_css[:50] if left_css else None}...")

    # Skip sync state check when using --override to force CSS update
    if not skip_sync_state and external_id:
        state = BustimesSyncState.objects.filter(
            object_type="livery", external_id=external_id, local_model="vehicles.livery"
        ).first()
        if state and state.local_pk:
            livery = Livery.objects.filter(pk=state.local_pk).first()
            if livery:
                if debug:
                    print(f"DEBUG: Found livery by sync state: {livery.name} (ID: {livery.id})")
                return livery

    # First try to match by CSS exactly (both left and right)
    if left_css:
        css_values = [left_css]
        try:
            minified_left_css = Livery.minify(left_css)
        except Exception:
            minified_left_css = ""
        if minified_left_css and minified_left_css not in css_values:
            css_values.append(minified_left_css)

        right_css_values = [right_css] if right_css else []
        if right_css:
            try:
                minified_right_css = Livery.minify(right_css)
            except Exception:
                minified_right_css = ""
            if minified_right_css and minified_right_css not in right_css_values:
                right_css_values.append(minified_right_css)

        # Try to find exact CSS match (both left and right)
        for css_value in css_values:
            if right_css_values:
                for right_css_value in right_css_values:
                    livery = Livery.objects.filter(left_css=css_value, right_css=right_css_value).first()
                    if livery:
                        if debug:
                            print(f"DEBUG: Found livery by CSS match: {livery.name} (ID: {livery.id})")
                        return livery
            else:
                livery = Livery.objects.filter(left_css=css_value).first()
                if livery:
                    if debug:
                        print(f"DEBUG: Found livery by left CSS match: {livery.name} (ID: {livery.id})")
                    return livery

    # If no CSS match, try to find by name and check if CSS matches
    if name:
        livery = Livery.objects.filter(name__iexact=name).first()
        if livery and left_css:
            # Check if the existing livery has the same CSS
            css_matches = False
            if livery.left_css and livery.left_css == left_css:
                if right_css:
                    css_matches = livery.right_css == right_css
                else:
                    css_matches = True
            
            if css_matches:
                if debug:
                    print(f"DEBUG: Found livery by name with matching CSS: {livery.name} (ID: {livery.id})")
                return livery
            else:
                # CSS doesn't match - will create a new livery below
                if debug:
                    print(f"DEBUG: Found livery by name but CSS doesn't match, will create new: {livery.name} (ID: {livery.id})")
                    print(f"DEBUG: Existing left_css: {livery.left_css[:50] if livery.left_css else None}...")
                    print(f"DEBUG: New left_css: {left_css[:50]}...")
        elif livery and not left_css:
            # No new CSS, return existing livery
            if debug:
                print(f"DEBUG: Found livery by name with no new CSS: {livery.name} (ID: {livery.id})")
            return livery

    # If no name match, create a new livery with the Bustimes CSS
    if name and left_css:
        if debug:
            print(f"DEBUG: Creating new livery: {name}")
        livery = Livery(
            name=name,
            show_name=True,
            colour=livery_data["colour"],
            left_css=left_css,
            right_css=right_css or left_css,
            published=True,
            external_id=external_id,
        )
        livery.save()
        if debug:
            print(f"DEBUG: Created new livery: {livery.name} (ID: {livery.id})")
        return livery

    if debug:
        print(f"DEBUG: Failed to resolve livery - name={name}, left_css={bool(left_css)}")
    return None


def resolve_vehicle_type(value: Any) -> VehicleType | None:
    if isinstance(value, dict):
        name = compact_text(value.get("name") or value.get("description"))
        style = compact_text(value.get("style"))
        fuel = compact_text(value.get("fuel"))
    else:
        name = compact_text(value)
        style = None
        fuel = None
    if not name:
        return None
    vehicle_type, created = VehicleType.objects.get_or_create(name=name)
    # Update style and fuel if provided and different
    if not created:
        dirty = False
        if style and vehicle_type.style != style:
            vehicle_type.style = style
            dirty = True
        if fuel and vehicle_type.fuel != fuel:
            vehicle_type.fuel = fuel
            dirty = True
        if dirty:
            vehicle_type.save()
    else:
        # Set style and fuel on newly created vehicle type
        if style:
            vehicle_type.style = style
        if fuel:
            vehicle_type.fuel = fuel
        vehicle_type.save()
    return vehicle_type


def resolve_garage(value: Any, operator: Operator | None = None) -> Garage | None:
    if isinstance(value, dict):
        garage_id = compact_text(value.get("id"))
        if garage_id:
            garage = Garage.objects.filter(pk=garage_id).first()
            if garage:
                return garage
        value = (
            value.get("external_id")
            or value.get("code")
            or value.get("name")
        )
    value = compact_text(value)
    if not value:
        return None

    garages = Garage.objects.all()
    if operator:
        operator_garage = garages.filter(operator=operator).filter(
            Q(external_id__iexact=value) | Q(code__iexact=value) | Q(name__iexact=value)
        ).first()
        if operator_garage:
            return operator_garage

    return garages.filter(
        Q(external_id__iexact=value) | Q(code__iexact=value) | Q(name__iexact=value)
    ).first()


def resolve_or_create_garage(value: Any, operator: Operator | None = None) -> Garage | None:
    if isinstance(value, dict):
        # Don't check by ID - we want exact name matching
        name = compact_text(value.get("name"))
        code = compact_text(value.get("code"))
        external_id = compact_text(value.get("external_id"))
    else:
        name = compact_text(value)
        code = None
        external_id = None

    if not name:
        return None

    # Try to find existing garage by exact name match
    garage = Garage.objects.filter(name=name).first()
    if garage:
        return garage

    # If not found and operator is provided, create new garage
    if operator:
        # Only include external_id if it's not empty to avoid unique constraint violations
        garage_data = {
            "name": name,
            "operator": operator,
            "code": code or name,
        }
        if external_id:
            garage_data["external_id"] = external_id
        garage = Garage.objects.create(**garage_data)
        return garage

    return None


def resolve_vehicle(item: dict[str, Any]) -> Vehicle | None:
    external_id = api_id(item)
    code = VehicleCode.objects.filter(scheme=BUSTIMES_SCHEME, code=external_id).select_related("vehicle").first()
    if code:
        return code.vehicle

    vehicle_data = item.get("vehicle") or {}
    reg = compact_registration(item.get("reg") or item.get("registration") or vehicle_data.get("reg"))
    vehicle_code = compact_text(
        item.get("code")
        or item.get("fleet_code")
        or item.get("fleet_number")
        or vehicle_data.get("code")
        or vehicle_data.get("fleet_code")
        or vehicle_data.get("fleet_number")
    )
    operator = resolve_operator(item.get("operator"))
    vehicles = Vehicle.objects.all()
    if operator:
        vehicles = vehicles.filter(operator=operator)
    if vehicle_code:
        vehicle = vehicles.filter(code__iexact=vehicle_code).first()
        if vehicle:
            return vehicle
    if reg:
        vehicle = vehicles.filter(reg__iexact=reg).first()
        if vehicle:
            return vehicle
    return None


def resolve_service_for_journey(item: dict[str, Any], vehicle: Vehicle | None, trip: Trip | None) -> Service | None:
    if trip and trip.route and trip.route.service_id:
        return trip.route.service
    route_name = compact_text(item.get("route_name"))
    if not route_name:
        return None
    services = Service.objects.filter(current=True, line_name__iexact=route_name)
    if vehicle and vehicle.operator_id:
        services = services.filter(operator=vehicle.operator_id)
    try:
        return services.get()
    except (Service.DoesNotExist, Service.MultipleObjectsReturned):
        return services.first()


def locally_edited_vehicle_fields(vehicle: Vehicle) -> set[str]:
    fields: set[str] = set()
    if getattr(vehicle, "locked", False):
        return {
            "operator",
            "vehicle_type",
            "livery",
            "fleet_number",
            "fleet_code",
            "reg",
            "prev_registration",
            "withdrawn",
            "preserved",
            "fleet_support_vehicle",
            "vor",
            "awaiting_delivery",
            "trainer_vehicle",
            "demonstrator",
            "garage",
            "name",
            "branding",
            "notes",
            "data",
            "features",
        }
    if not vehicle.pk:
        return fields
    operator = getattr(vehicle, "operator", None)
    operator_external_id = (getattr(operator, "external_id", None) or "").strip()
    if (
        operator
        and operator_external_id.startswith("stagecoach-garage:")
    ):
        fields.add("operator")
    revisions = VehicleRevision.objects.filter(
        vehicle=vehicle,
        pending=False,
        disapproved=False,
        approved_at__isnull=False,
    ).filter(Q(user__isnull=False) | Q(approved_by__isnull=False))
    for revision in revisions:
        if revision.from_operator_id or revision.to_operator_id:
            fields.add("operator")
        if revision.from_type_id or revision.to_type_id:
            fields.add("vehicle_type")
        if revision.from_livery_id or revision.to_livery_id:
            fields.add("livery")
        if revision.features.exists():
            fields.add("features")
        for key in revision.changes or {}:
            key = key.replace("fleet number", "fleet_code")
            if key == "removed from list":
                key = "withdrawn"
            fields.add(key)
    return fields


def parse_api_datetime(value: Any):
    value = compact_text(value)
    if not value:
        return None
    return parse_datetime(value)


def point_from_location(value: Any):
    if not value or len(value) != 2:
        return None
    lon, lat = value
    if lon is None or lat is None:
        return None
    return Point(float(lon), float(lat))
