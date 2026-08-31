import datetime
import json
import logging
import os
from functools import lru_cache
from itertools import pairwise, groupby
from types import SimpleNamespace
from urllib.parse import unquote
from functools import partial
from http import HTTPStatus
import subprocess
import xmltodict
import requests
from collections import defaultdict
from fleet.models import PinnedOperator
from fleet.exporters.xlsx import build_basic_fleet_workbook, workbook_bytes
from fleet.completion import (
    annotate_logged_state,
    annotate_photographed_state,
    get_completion_summary_for_queryset,
    has_vehicle_been_logged,
    has_vehicle_been_driven,
    has_vehicle_been_photographed,
    create_driving_log,
    set_ride_log_state,
    sync_ride_logs_for_queryset,
)
from fleet.models import FleetPhotoLog
from django.db.models import Sum
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.auth.models import Permission
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, BadRequest
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, connection, transaction
from django.db.models import Avg, Case, CharField, Count, F, Max, Prefetch, Q, When, Value
from django.db.models.aggregates import StringAgg
from django.db.models.functions import Coalesce, Now
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.cache import get_conditional_response, set_response_etag
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from django.utils.decorators import method_decorator
from django.views.generic.detail import DetailView
import numpy as np
from haversine import Unit, haversine_vector
from redis.exceptions import ConnectionError
from sql_util.utils import Exists, SubqueryMax, SubqueryMin

from accounts.models import User
from accounts.notifications import notify_request_created
from busstops.models import (
    SERVICE_ORDER_REGEX,
    DataSource,
    DataChangeLog,
    Operator,
    OperatorGroup,
    Service,
    ServiceCode,
    StopUsage,
)
from busstops.utils import (
    build_depot_map_html,
    get_operator_depots,
    get_operator_social_links,
    serialize_depot_map_points,
)
from bustimes.models import Garage, Route, StopTime
from bustimes.utils import contiguous_stoptimes_only, get_other_trips_in_block
from photos.forms import PhotoForm
from photos.models import Photo
from photos.utils import add_flickr_photo

from . import filters, forms
from .models import (
    BusGroup,
    HistoricalVehicle,
    Livery,
    SiriSubscription,
    Vehicle,
    VehicleCode,
    VehicleNamePage,
    VehicleJourney,
    VehicleLocation,
    VehicleRevision,
    VehicleRevisionFeature,
    VehicleReview,
    VehicleReviewReport,
    VehicleType,
    VehicleFeature,
)
from .moderation import find_blocked_review_phrases
from .rtpi import add_progress_and_delay
from .tasks import handle_siri_post
from .utils import apply_revision, get_revision, redis_client  # calculate_bearing,
from fleet.models import FleetRideLog, FleetDrivingLog


REQUEST_SOURCES = {
    "vehicle_request": "Vehicle",
    "stop_request": "Stop",
    "service_request": "Service",
    "operator_request": "Operator",
    "vehicle_type_request": "Vehicle Model",
    "photo_suggestion": "Photo Suggestion",
}


REQUEST_TARGET_MODELS = {
    "vehicle_request": Vehicle,
    "service_request": Service,
    "operator_request": Operator,
    "vehicle_type_request": VehicleType,
    "photo_suggestion": Vehicle,
}

TRUSTED_REQUEST_APPROVAL_SOURCES = {
    "stop_request",
    "service_request",
    "vehicle_request",
    "vehicle_type_request",
    "photo_suggestion",
}


def get_redirect_view(*args, **kwargs):
    def redirect_view(request):
        return redirect(*args, **kwargs)

    return redirect_view


class Vehicles:
    """for linking to an operator's /vehicles page (fleet list) in a breadcrumb list"""

    def __init__(self, vehicle=None, operator=None):
        self.vehicle = vehicle
        self.operator = operator or vehicle.operator

    def __str__(self):
        return "Vehicles"

    def get_absolute_url(self):
        url = reverse("operator_vehicles", args=(self.operator.slug,))
        if self.vehicle:
            url = f"{url}#{self.vehicle.slug}"
        return url


class RequestsPage:
    def __str__(self):
        return "Requests"

    def get_absolute_url(self):
        return reverse("requests_home")


class DashboardPage:
    def __str__(self):
        return "Dashboard"

    def get_absolute_url(self):
        return reverse("dashboard_home")


class DashboardBreadcrumbItem:
    def __init__(self, label, url):
        self.label = label
        self.url = url

    def __str__(self):
        return self.label

    def get_absolute_url(self):
        return self.url


def require_superuser(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if not request.user.is_superuser:
        raise PermissionDenied


def require_dashboard_access(request):
    if not request.user.is_authenticated:
        raise PermissionDenied
    if request.user.is_superuser:
        return
    if any(
        item["can_add"] or item["manage_url"]
        for section in get_dashboard_model_sections(request)
        for item in section["items"]
    ):
        return
    raise PermissionDenied





DASHBOARD_MODEL_ORDER = {
    "accounts.user": 1,
    "accounts.operatoruser": 2,
    "accounts.invitation": 3,
    "busstops.organisation": 10,
    "busstops.operatorgroup": 11,
    "busstops.operator": 12,
    "busstops.service": 13,
    "busstops.blogpost": 14,
    "busstops.blogtag": 15,
    "vehicles.livery": 20,
    "vehicles.vehicle": 21,
    "vehicles.vehicletype": 22,
    "vehicles.vehicletypegroup": 23,
    "vehicles.vehiclefeature": 24,
    "vehicles.busgroup": 25,
    "busstops.manufacturer": 30,
    "busstops.manufacturersite": 31,
    "busstops.datasource": 32,
    "busstops.region": 40,
    "busstops.district": 41,
    "busstops.locality": 42,
    "busstops.adminarea": 43,
}

EXCLUDED_DASHBOARD_APPS = {
    "admin",
    "auth",
    "contenttypes",
    "sessions",
}


def get_dashboard_model_sections(request):
    grouped = defaultdict(list)
    for model, model_admin in admin.site._registry.items():
        meta = model._meta
        if meta.app_label in EXCLUDED_DASHBOARD_APPS:
            continue
        if not model_admin.has_module_permission(request):
            continue

        label = meta.label_lower
        app_title = meta.app_config.verbose_name.title()
        try:
            changelist_url = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")
        except NoReverseMatch:
            changelist_url = ""
        can_manage = model_admin.has_view_permission(request) or model_admin.has_change_permission(
            request
        )

        item = {
            "label": label,
            "title": meta.verbose_name.title(),
            "plural_title": meta.verbose_name_plural.title(),
            "description": f"Add or manage {meta.verbose_name_plural}.",
            "app_title": app_title,
            "app_label": meta.app_label,
            "model_name": meta.model_name,
            "model": model,
            "model_admin": model_admin,
            "add_url": reverse(
                "dashboard_add_model",
                kwargs={"app_label": meta.app_label, "model_name": meta.model_name},
            ),
            "manage_url": changelist_url if can_manage else "",
            "can_add": model_admin.has_add_permission(request),
            "order": DASHBOARD_MODEL_ORDER.get(label, 1000),
        }
        grouped[app_title].append(item)

    sections = []
    for app_title, items in grouped.items():
        items.sort(key=lambda item: (item["order"], item["plural_title"]))
        sections.append({"title": app_title, "items": items})
    sections.sort(key=lambda section: min(item["order"] for item in section["items"]))
    return sections


def get_dashboard_model_item(request, app_label, model_name):
    for section in get_dashboard_model_sections(request):
        for item in section["items"]:
            if item["app_label"] == app_label and item["model_name"] == model_name:
                return item
    raise Http404


def get_dashboard_form_sections(model_admin, request, form):
    sections = []
    seen = set()
    fieldsets = model_admin.get_fieldsets(request)
    for title, options in fieldsets:
        field_names = [
            name
            for name in flatten_fieldsets(((title, options),))
            if name in form.fields and name not in seen
        ]
        if not field_names:
            continue
        seen.update(field_names)
        sections.append(
            {
                "title": title or "",
                "fields": [form[name] for name in field_names],
                "description": options.get("description", ""),
            }
        )

    leftover = [form[name] for name in form.fields if name not in seen]
    if leftover:
        sections.append({"title": "Other fields", "fields": leftover, "description": ""})
    return sections


class LiveriesPage:
    def __str__(self):
        return "Liveries"

    def get_absolute_url(self):
        return reverse("livery_list")


@require_safe
def vehicles(request):
    """index of recently AVL-enabled operators, etc"""

    search_query = request.GET.get("search", "").strip()
    vehicle_mode_filter = request.GET.get("vehicle_mode", "")

    operators = Operator.objects.filter(
        ceased_operations_on__isnull=True
    ).only("name", "slug", "vehicle_mode")

    # Filter by search query
    if search_query:
        operators = operators.filter(name__icontains=search_query)

    # Filter by vehicle mode
    if vehicle_mode_filter:
        operators = operators.filter(vehicle_mode=vehicle_mode_filter)

    # Annotate operators with whether they have non-withdrawn vehicles
    operators = operators.annotate(
        has_vehicles=Exists(
            "vehicle",
            filter=Q(**current_fleet_filter(withdrawn=False, preserved=False)),
        )
    )

    new_operators = operators.annotate(
        min=SubqueryMin("vehicle__id"),
    ).order_by("-min")[:36]

    operator_journeys = VehicleJourney.objects.filter(
        latest_vehicle__operator=OuterRef("noc")
    )

    day_ago = timezone.now() - datetime.timedelta(days=1)
    status = (
        operators.filter(
            Exists(operator_journeys),
            ~Exists(operator_journeys.filter(datetime__gte=day_ago)),
        )
        .annotate(
            last_seen=SubqueryMax("vehicle__latest_journey__datetime"),
        )
        .order_by("-last_seen")
    )

    # Get unique vehicle modes for dropdown
    vehicle_modes = (
        Operator.objects.filter(
            ceased_operations_on__isnull=True,
            vehicle_mode__isnull=False,
        )
        .exclude(vehicle_mode="")
        .values_list("vehicle_mode", flat=True)
        .distinct()
        .order_by("vehicle_mode")
    )

    return render(
        request,
        "vehicles.html",
        {
            "status": list(status),
            "new_operators": list(new_operators),
            "operators": list(operators),
            "search_query": search_query,
            "vehicle_mode_filter": vehicle_mode_filter,
            "vehicle_modes": list(vehicle_modes),
        },
    )


@cache_control(max_age=3600)
def liveries_css(request, version=0):
    styles = []
    liveries = Livery.objects.filter(published=True).order_by("left_css")
    for _, liveries in groupby(liveries, lambda livery: livery.right_css):
        liveries = list(liveries)
        styles += liveries[0].get_styles([livery.id for livery in liveries])
    styles = "".join(styles)
    completed_process = subprocess.run(
        ["lightningcss", "--minify"], input=styles.encode(), capture_output=True
    )
    styles = completed_process.stdout
    return HttpResponse(styles, content_type="text/css")


features_string_agg = StringAgg(
    "features__name",
    Value(", "),
    order_by=["features__name"],
    default="",
    filter=Q(features__category=VehicleFeature.Category.FEATURE),
)

accessibility_string_agg = StringAgg(
    "features__name",
    Value(", "),
    order_by=["features__name"],
    default="",
    filter=Q(features__category=VehicleFeature.Category.ACCESSIBILITY),
)

BUSTIMES_SCHEME = "bustimes"
BUSTIMES_SLUG_SCHEME = "bustimes-slug"
BUSTIMES_SOURCE_NAME = "Bustimes API"
HIDDEN_VEHICLE_DATA_COLUMNS = {
    BUSTIMES_SOURCE_NAME,
    "Rear advert",
    "rear advert",
    "rear_advert",
}


def get_vehicle_column_value(vehicle, column):
    data = vehicle.data or {}
    return data.get(column.slug) or data.get(column.name) or ""


def get_operator_vehicle_columns(operator, vehicles):
    if operator:
        defined_columns = list(
            operator.vehicle_columns.order_by("display_order", "name")
        )
        if defined_columns:
            return defined_columns

    keys = sorted(
        key
        for vehicle in vehicles
        if vehicle.data
        for key in vehicle.data
        if key not in HIDDEN_VEHICLE_DATA_COLUMNS
    )
    return [SimpleNamespace(name=key, slug=key) for key in dict.fromkeys(keys)]


def get_bustimes_source():
    return DataSource.objects.filter(name=BUSTIMES_SOURCE_NAME).first()


def get_remote_vehicle_ids(local_ids):
    codes = VehicleCode.objects.filter(
        scheme=BUSTIMES_SCHEME, vehicle_id__in=local_ids
    ).values_list("vehicle_id", "code")
    return [code for _, code in sorted(codes)]


def get_remote_service_ids(local_ids):
    codes = ServiceCode.objects.filter(
        scheme=BUSTIMES_SCHEME, service_id__in=local_ids
    ).values_list("service_id", "code")
    return [code for _, code in sorted(codes)]


def get_bustimes_vehicle_json_params(request):
    params = request.GET.copy()

    if "id" in params:
        try:
            local_ids = [int(value) for value in params["id"].split(",") if value]
        except ValueError:
            raise BadRequest
        remote_ids = get_remote_vehicle_ids(local_ids)
        if not remote_ids:
            return None
        params["id"] = ",".join(remote_ids)

    if "service" in params:
        try:
            local_ids = [
                int(value) for value in params["service"].split(",") if value
            ]
        except ValueError:
            raise BadRequest
        remote_ids = get_remote_service_ids(local_ids)
        if not remote_ids:
            return None
        params["service"] = ",".join(remote_ids)

    return params


def get_bustimes_vehicle_items(request):
    params = get_bustimes_vehicle_json_params(request)
    if params is None:
        return []

    response = requests.get(
        settings.BUSTIMES_VEHICLES_JSON_URL,
        params=params,
        timeout=10,
        headers={
            "User-Agent": getattr(
                settings, "BUSTIMES_API_USER_AGENT", "betterfleet/1.0"
            )
        },
    )
    response.raise_for_status()
    return response.json()


def parse_live_datetime(value):
    if isinstance(value, datetime.datetime):
        return value
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, datetime.timezone.utc)
    return parsed


def append_live_location(item, vehicle, journey):
    if not redis_client or not item.get("coordinates") or not item.get("datetime"):
        return

    when = parse_live_datetime(item["datetime"])
    if when is None:
        return

    delay = item.get("delay")
    delay_delta = None
    if delay is not None:
        delay_delta = datetime.timedelta(seconds=float(delay))

    lon, lat = item["coordinates"]
    location = VehicleLocation(
        Point(float(lon), float(lat)),
        heading=item.get("heading"),
        delay=delay_delta,
        block=item.get("block"),
    )
    location.id = vehicle.id
    location.datetime = when
    location.journey = journey

    try:
        key, appendage = location.get_appendage()
        redis_client.set(
            f"vehicle{vehicle.id}",
            json.dumps(item, cls=DjangoJSONEncoder),
            ex=600,
        )
        redis_client.rpush(key, appendage)
        redis_client.expire(key, 60 * 60 * 48)
        if vehicle.operator_id:
            redis_client.sadd(f"operator{vehicle.operator_id}vehicles", vehicle.id)
            redis_client.expire(f"operator{vehicle.operator_id}vehicles", 600)
        if journey.service_id:
            redis_client.sadd(f"service{journey.service_id}vehicles", vehicle.id)
            redis_client.expire(f"service{journey.service_id}vehicles", 600)
        try:
            redis_client.geoadd(
                "vehicle_location_locations",
                (float(lon), float(lat), vehicle.id),
            )
        except TypeError:
            redis_client.geoadd(
                "vehicle_location_locations",
                {vehicle.id: (float(lon), float(lat))},
            )
    except Exception as exc:
        logging.debug("Could not cache Bustimes live vehicle location: %s", exc)


def normalize_bustimes_vehicle_items(items):
    remote_vehicle_ids = [str(item.get("id")) for item in items if item.get("id")]
    remote_journey_ids = [
        str(item.get("journey_id")) for item in items if item.get("journey_id")
    ]

    vehicle_codes = list(
        VehicleCode.objects.filter(scheme=BUSTIMES_SCHEME, code__in=remote_vehicle_ids)
        .select_related("vehicle")
        .only("code", "vehicle")
    )
    vehicles = (
        apply_vehicle_schema_compat(
            Vehicle.objects.filter(id__in=[code.vehicle_id for code in vehicle_codes])
        )
        .select_related("vehicle_type", "livery")
        .annotate(feature_names=features_string_agg, colour=F("livery__colour"))
    )
    vehicles_by_id = vehicles.in_bulk()
    vehicles_by_remote_id = {
        str(code.code): vehicles_by_id[code.vehicle_id]
        for code in vehicle_codes
        if code.vehicle_id in vehicles_by_id
    }

    source = get_bustimes_source()
    journeys = VehicleJourney.objects.none()
    if source and remote_journey_ids:
        journeys = VehicleJourney.objects.filter(
            source=source, code__in=remote_journey_ids
        ).select_related("service", "trip__route", "vehicle")
    journeys_by_remote_id = {str(journey.code): journey for journey in journeys}

    local_items = []
    for remote_item in items:
        remote_vehicle_id = str(remote_item.get("id") or "")
        vehicle = vehicles_by_remote_id.get(remote_vehicle_id)
        if not vehicle:
            continue

        item = dict(remote_item)
        item["id"] = vehicle.id
        item["vehicle"] = vehicle.get_json()

        remote_journey_id = str(item.get("journey_id") or "")
        journey = journeys_by_remote_id.get(remote_journey_id)
        if journey:
            item["journey_id"] = journey.id
            item["destination"] = item.get("destination") or journey.destination
            if journey.trip_id:
                item["trip_id"] = journey.trip_id
            if journey.service_id:
                service_url = (
                    journey.service.get_absolute_url()
                    if hasattr(journey.service, "get_absolute_url")
                    else f"/services/{journey.service.slug}"
                )
                item["service_id"] = journey.service_id
                item["service"] = {
                    "url": service_url,
                    "line_name": (
                        journey.trip.route.line_name
                        if journey.trip_id and journey.trip and journey.trip.route_id
                        else journey.route_name
                    ),
                }
            elif journey.route_name:
                item["service"] = {"line_name": journey.route_name}
            append_live_location(item, vehicle, journey)
        else:
            item.pop("journey_id", None)

        local_items.append(item)

    return local_items


def get_vehicle_order(vehicle) -> tuple[str, int, str]:
    if vehicle.notes == "Spare ticket machine":
        return ("", vehicle.fleet_number or 99999, vehicle.code)

    if vehicle.fleet_number:
        return ("", vehicle.fleet_number)

    # age-based ordering
    if not vehicle.fleet_code and len(reg := vehicle.reg) == 7 and reg[-3:].isalpha():
        if reg[:2].isalpha() and reg[2:4].isdigit():
            year = int(reg[2:4])
            if year > 50:
                return ("Z", (year - 50) * 2 + 1, "")  # year 64 (september 2014) - 29
            return ("Z", year * 2, "")  # year 14 (march 2014) - 28

        if reg[1:4].isdigit():
            return reg[0], int(reg[1:4]), reg[-3:]

    prefix, number, suffix = SERVICE_ORDER_REGEX.match(
        vehicle.fleet_code or vehicle.code
    ).groups()
    number = int(number) if number else 0
    if " " in prefix:  # McGill's
        return (suffix, number, prefix)
    return (prefix, number, suffix)


@lru_cache(maxsize=1)
def _vehicle_db_columns():
    try:
        with connection.cursor() as cursor:
            return {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, Vehicle._meta.db_table
                )
            }
    except Exception:
        return {
            field.column
            for field in Vehicle._meta.fields
            if getattr(field, "column", None)
        }


@lru_cache(maxsize=1)
def _missing_vehicle_field_names():
    columns = _vehicle_db_columns()
    missing = []
    for field in Vehicle._meta.concrete_fields:
        column = getattr(field, "column", None)
        if column and column not in columns:
            missing.append(field.name)
    return tuple(missing)


def apply_vehicle_schema_compat(queryset, prefix=""):
    missing = _missing_vehicle_field_names()
    if missing:
        queryset = queryset.defer(*(f"{prefix}{name}" for name in missing))
    return queryset


def current_fleet_filter(**filters):
    columns = _vehicle_db_columns()
    unsupported = {
        "withdrawn": "withdrawn",
        "preserved": "preserved",
        "operator": "operator_id",
        "operator__group": "operator_id",
    }
    for key, column in unsupported.items():
        if key in filters and column not in columns:
            filters.pop(key)
    if "historical_fleet_id" in columns:
        filters["historical_fleet__isnull"] = True
    return filters


@require_http_methods(["GET", "POST"])
def operator_vehicles(request, slug=None, group_slug=None, historical=False):
    """fleet list"""
    active_operator_tab = "depots" if request.GET.get("tab") == "depots" else (
        "historical" if historical else "fleet"
    )
    show_dvla_status = request.GET.get("show_dvla_status") == "1"
    view_mode = request.GET.get("view", "table")  # 'table' or 'card'
    historical_year_cards = []
    selected_historical_year = None
    show_completion = request.user.is_authenticated
    sort_option = request.GET.get("sort", "")
    mass_log_mode = (
        show_completion
        and request.user.is_authenticated
        and slug is not None
        and not group_slug
        and (
            request.POST.get("mass_log_save")
            or request.GET.get("mass_log") == "1"
        )
    )

    operators = Operator.objects.select_related("region", "group")
    if group_slug:
        try:
            group = OperatorGroup.objects.get(slug=group_slug)
        except OperatorGroup.DoesNotExist:
            # cool URIs don't change
            group = get_object_or_404(OperatorGroup, name=group_slug)
        operators = group.operator_set.in_bulk()
        vehicles = apply_vehicle_schema_compat(
            Vehicle.objects.filter(
                operator__group=group,
                operator__ceased_operations_on__isnull=True,
                **current_fleet_filter(),
            ).select_related("livery")
        )
        if not historical and "withdrawn" not in request.GET:
            vehicles = vehicles.filter(**current_fleet_filter(withdrawn=False))
        vehicles = vehicles.annotate(
            feature_names=features_string_agg,
            accessibility_names=accessibility_string_agg,
            livery_name=Case(When(livery__show_name=True, then="livery__name")),
            vehicle_type_name=F("vehicle_type__name"),
            garage_name=Case(
                When(garage__name="", then="garage__code"),
                default="garage__name",
            ),
        )
        vehicles = annotate_logged_state(vehicles, request.user)
        vehicles = annotate_photographed_state(vehicles, request.user)
        vehicles = vehicles.prefetch_related(
            Prefetch(
                "reviews",
                queryset=VehicleReview.objects.filter(
                    status=VehicleReview.Status.PUBLISHED
                ),
            )
        )
        active_operators = group.operator_set.filter(
            ceased_operations_on__isnull=True
        ).select_related("region").order_by("name")
        ceased_operators = group.operator_set.filter(
            ceased_operations_on__isnull=False
        ).select_related("region").order_by("ceased_operations_on", "name")
    elif slug:
        group = None
        try:
            operator = operators.get(slug=slug.lower())
        except Operator.DoesNotExist:
            operator = get_object_or_404(
                operators, operatorcode__code=slug, operatorcode__source__name="slug"
            )
        if historical:
            vehicles = apply_vehicle_schema_compat(
                operator.historical_vehicle_set.select_related("operator", "livery")
            )
            vehicles = vehicles.annotate(
                feature_names=features_string_agg,
                accessibility_names=accessibility_string_agg,
                livery_name=Case(When(livery__show_name=True, then="livery__name")),
                vehicle_type_name=F("vehicle_type__name"),
                garage_name=Case(
                    When(garage__name="", then="garage__code"),
                    default="garage__name",
                ),
            )
            vehicles = annotate_logged_state(vehicles, request.user)
            vehicles = annotate_photographed_state(vehicles, request.user)
            vehicles = vehicles.prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=VehicleReview.objects.filter(
                        status=VehicleReview.Status.PUBLISHED
                    ),
                )
            )
            selected_year_param = request.GET.get("year", "")
            if selected_year_param.isdigit():
                selected_historical_year = int(selected_year_param)
                vehicles = vehicles.filter(historical_fleet_year=selected_historical_year)
            historical_year_cards_queryset = (
                operator.historical_vehicle_set.filter(
                    historical_fleet_year__isnull=False
                )
                .values("historical_fleet_year")
                .annotate(vehicle_count=Count("id"))
            )
            if "historical_fleet_creator" in _vehicle_db_columns():
                historical_year_cards_queryset = historical_year_cards_queryset.annotate(
                    creator=Max("historical_fleet_creator")
                )
            else:
                historical_year_cards_queryset = historical_year_cards_queryset.annotate(
                    creator=Value("", output_field=CharField())
                )
            historical_year_cards = list(
                historical_year_cards_queryset.order_by("-historical_fleet_year")
            )
            # Get liveries for each historical year
            for card in historical_year_cards:
                year_liveries = (
                    operator.historical_vehicle_set.filter(
                        historical_fleet_year=card["historical_fleet_year"]
                    )
                    .exclude(livery__isnull=True)
                    .values("livery__id", "livery__left_css")
                    .distinct()
                )
                card["liveries"] = list(year_liveries)
        else:
            # Include vehicles owned by this operator
            vehicles = Vehicle.objects.filter(operator=operator, **current_fleet_filter()).select_related("livery", "operator")

            # Apply filters
            selected_garage = None
            selected_livery = None
            selected_vehicle_type = None
            logged_filter = request.GET.get("logged")
            
            if not historical:
                # Withdrawn filter
                withdrawn_filter = request.GET.get("withdrawn")
                if withdrawn_filter == "0":
                    vehicles = vehicles.filter(**current_fleet_filter(withdrawn=False))
                elif withdrawn_filter != "1":
                    # Default behavior: hide withdrawn unless explicitly shown
                    vehicles = vehicles.filter(**current_fleet_filter(withdrawn=False))
                
                garage_id = request.GET.get("garage")
                if garage_id and garage_id.isdigit():
                    selected_garage = Garage.objects.filter(
                        pk=int(garage_id), operators=operator
                    ).first()
                    if selected_garage:
                        vehicles = vehicles.filter(garage=selected_garage)
                    else:
                        vehicles = vehicles.none()
                elif garage_id:
                    vehicles = vehicles.none()
                
                # Livery filter
                livery_id = request.GET.get("livery")
                if livery_id and livery_id.isdigit():
                    selected_livery = Livery.objects.filter(pk=int(livery_id)).first()
                    if selected_livery:
                        vehicles = vehicles.filter(livery=selected_livery)
                    else:
                        vehicles = vehicles.none()
                
                # Vehicle type filter
                vehicle_type_id = request.GET.get("vehicle_type")
                if vehicle_type_id and vehicle_type_id.isdigit():
                    selected_vehicle_type = VehicleType.objects.filter(pk=int(vehicle_type_id)).first()
                    if selected_vehicle_type:
                        vehicles = vehicles.filter(vehicle_type=selected_vehicle_type)
                    else:
                        vehicles = vehicles.none()
                
                # Logged filter (for authenticated users)
                if logged_filter and request.user.is_authenticated:
                    if logged_filter == "ridden":
                        vehicles = vehicles.filter(has_been_ridden=True)
                    elif logged_filter == "photographed":
                        vehicles = vehicles.filter(has_been_photographed=True)
                    elif logged_filter == "not_ridden":
                        vehicles = vehicles.filter(has_been_ridden=False)
                    elif logged_filter == "not_photographed":
                        vehicles = vehicles.filter(has_been_photographed=False)

            if not historical and "withdrawn" not in request.GET and not withdrawn_filter:
                vehicles = vehicles.filter(**current_fleet_filter(withdrawn=False))

            # Also include vehicles on loan to this operator
            loaned_vehicles = Vehicle.objects.filter(operated_by=operator, **current_fleet_filter()).select_related("livery", "operator")
            
            # Apply the same filters to loaned vehicles as owned vehicles
            if not historical:
                # Withdrawn filter
                withdrawn_filter = request.GET.get("withdrawn")
                if withdrawn_filter == "0":
                    loaned_vehicles = loaned_vehicles.filter(**current_fleet_filter(withdrawn=False))
                elif withdrawn_filter != "1":
                    # Default behavior: hide withdrawn unless explicitly shown
                    loaned_vehicles = loaned_vehicles.filter(**current_fleet_filter(withdrawn=False))
                
                garage_id = request.GET.get("garage")
                if garage_id and garage_id.isdigit():
                    selected_garage = Garage.objects.filter(
                        pk=int(garage_id), operators=operator
                    ).first()
                    if selected_garage:
                        loaned_vehicles = loaned_vehicles.filter(garage=selected_garage)
                    else:
                        loaned_vehicles = loaned_vehicles.none()
                elif garage_id:
                    loaned_vehicles = loaned_vehicles.none()
                
                # Livery filter
                livery_id = request.GET.get("livery")
                if livery_id and livery_id.isdigit():
                    selected_livery = Livery.objects.filter(pk=int(livery_id)).first()
                    if selected_livery:
                        loaned_vehicles = loaned_vehicles.filter(livery=selected_livery)
                    else:
                        loaned_vehicles = loaned_vehicles.none()
                
                # Vehicle type filter
                vehicle_type_id = request.GET.get("vehicle_type")
                if vehicle_type_id and vehicle_type_id.isdigit():
                    selected_vehicle_type = VehicleType.objects.filter(pk=int(vehicle_type_id)).first()
                    if selected_vehicle_type:
                        loaned_vehicles = loaned_vehicles.filter(vehicle_type=selected_vehicle_type)
                    else:
                        loaned_vehicles = loaned_vehicles.none()
                
                # Logged filter (for authenticated users)
                if logged_filter and request.user.is_authenticated:
                    if logged_filter == "ridden":
                        loaned_vehicles = loaned_vehicles.filter(has_been_ridden=True)
                    elif logged_filter == "photographed":
                        loaned_vehicles = loaned_vehicles.filter(has_been_photographed=True)
                    elif logged_filter == "not_ridden":
                        loaned_vehicles = loaned_vehicles.filter(has_been_ridden=False)
                    elif logged_filter == "not_photographed":
                        loaned_vehicles = loaned_vehicles.filter(has_been_photographed=False)
            
            # Apply the same final filter to loaned vehicles
            if not historical and "withdrawn" not in request.GET and not withdrawn_filter:
                loaned_vehicles = loaned_vehicles.filter(**current_fleet_filter(withdrawn=False))

            # Apply annotations before union (Django doesn't support annotate after union)
            vehicles = vehicles.annotate(feature_names=features_string_agg)
            vehicles = vehicles.annotate(accessibility_names=accessibility_string_agg)
            vehicles = vehicles.annotate(
                pending_edits=Exists("vehiclerevision", filter=Q(pending=True)),
                livery_name=Case(When(livery__show_name=True, then="livery__name")),
                vehicle_type_name=F("vehicle_type__name"),
                garage_name=Case(
                    When(garage__name="", then="garage__code"),
                    default="garage__name",
                ),
            )
            vehicles = annotate_logged_state(vehicles, request.user)
            vehicles = annotate_photographed_state(vehicles, request.user)
            
            # Apply same annotations to loaned vehicles before union
            loaned_vehicles = loaned_vehicles.annotate(feature_names=features_string_agg)
            loaned_vehicles = loaned_vehicles.annotate(accessibility_names=accessibility_string_agg)
            loaned_vehicles = loaned_vehicles.annotate(
                pending_edits=Exists("vehiclerevision", filter=Q(pending=True)),
                livery_name=Case(When(livery__show_name=True, then="livery__name")),
                vehicle_type_name=F("vehicle_type__name"),
                garage_name=Case(
                    When(garage__name="", then="garage__code"),
                    default="garage__name",
                ),
            )
            loaned_vehicles = annotate_logged_state(loaned_vehicles, request.user)
            loaned_vehicles = annotate_photographed_state(loaned_vehicles, request.user)
            
            # Apply select_related before union (Django doesn't support select_related after union)
            if "latest_journey_id" in _vehicle_db_columns():
                vehicles = vehicles.select_related("latest_journey")
                loaned_vehicles = loaned_vehicles.select_related("latest_journey")
            
            # Apply prefetch_related before union (Django doesn't support prefetch_related after union)
            vehicles = vehicles.prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=VehicleReview.objects.filter(
                        status=VehicleReview.Status.PUBLISHED
                    ),
                )
            )
            loaned_vehicles = loaned_vehicles.prefetch_related(
                Prefetch(
                    "reviews",
                    queryset=VehicleReview.objects.filter(
                        status=VehicleReview.Status.PUBLISHED
                    ),
                )
            )
            
            # Note: Don't apply schema compatibility before union as defer() can cause column count mismatches
            # Schema compatibility will be applied after union if needed
            vehicles = vehicles.union(loaned_vehicles)
            
            # Apply schema compatibility after union
            vehicles = apply_vehicle_schema_compat(vehicles)

    if historical:
        vehicles = vehicles.order_by(
            "-historical_fleet_year", "fleet_number", "fleet_code", "reg", "code"
        )
    elif slug and not group_slug:
        # Apply custom sorting if specified
        if sort_option:
            if sort_option == "fleet_number_asc":
                vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")
            elif sort_option == "fleet_number_desc":
                vehicles = vehicles.order_by("-fleet_number", "-fleet_code", "-reg", "-code")
            elif sort_option == "type_asc":
                vehicles = vehicles.order_by("vehicle_type__name", "fleet_number", "fleet_code", "reg", "code")
            elif sort_option == "type_desc":
                vehicles = vehicles.order_by("-vehicle_type__name", "-fleet_number", "-fleet_code", "-reg", "-code")
            elif sort_option == "age_asc":
                # Oldest first - sort by year_of_manufacture ascending
                vehicles = vehicles.order_by("year_of_manufacture", "fleet_number", "fleet_code", "reg", "code")
            elif sort_option == "age_desc":
                # Newest first - sort by year_of_manufacture descending
                vehicles = vehicles.order_by("-year_of_manufacture", "-fleet_number", "-fleet_code", "-reg", "-code")
            else:
                # Default sorting
                has_fleet_numbers = operator.vehicle_set.filter(fleet_number__isnull=False).exists()
                if has_fleet_numbers:
                    vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")
                else:
                    vehicles = vehicles.order_by("vehicle_type__name", "fleet_code", "reg", "code")
        else:
            # Check if the operator has any fleet_number values set
            has_fleet_numbers = operator.vehicle_set.filter(fleet_number__isnull=False).exists()

            if has_fleet_numbers:
                vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")
            else:
                # No fleet numbers - sort by vehicle type
                vehicles = vehicles.order_by("vehicle_type__name", "fleet_code", "reg", "code")
    else:
        # Group view - default ordering
        vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")

    completion_summary = None
    if show_completion and slug and not group_slug:
        # Skip completion summary for union querysets (owned + loaned vehicles)
        # as filter() is not supported on union querysets
        if not historical:
            completion_summary = None
        else:
            completion_summary = get_completion_summary_for_queryset(vehicles, request.user)

    if request.method == "POST":
        if not mass_log_mode:
            raise PermissionDenied
        visible_vehicles = list(vehicles)
        created_logs, deleted_logs = sync_ride_logs_for_queryset(
            request.user,
            visible_vehicles,
            request.POST.getlist("logged_vehicle_ids"),
        )
        if created_logs or deleted_logs:
            messages.success(
                request,
                f"Saved ride logs: added {created_logs}, removed {deleted_logs}.",
            )
        else:
            messages.info(request, "No ride log changes were needed.")
        vehicle_ids = [vehicle.pk for vehicle in visible_vehicles]
        vehicles = Vehicle.objects.filter(pk__in=vehicle_ids)
        vehicles = vehicles.annotate(
            feature_names=features_string_agg,
            accessibility_names=accessibility_string_agg,
            livery_name=Case(When(livery__show_name=True, then="livery__name")),
            vehicle_type_name=F("vehicle_type__name"),
            garage_name=Case(
                When(garage__name="", then="garage__code"),
                default="garage__name",
            ),
        )
        vehicles = annotate_logged_state(vehicles, request.user)
        vehicles = annotate_photographed_state(vehicles, request.user)
        vehicles = vehicles.prefetch_related(
            Prefetch(
                "reviews",
                queryset=VehicleReview.objects.filter(
                    status=VehicleReview.Status.PUBLISHED
                ),
            )
        )
        if "latest_journey_id" in _vehicle_db_columns():
            vehicles = vehicles.select_related("latest_journey")
        vehicles = apply_vehicle_schema_compat(vehicles)
        
        if historical:
            vehicles = vehicles.order_by(
                "-historical_fleet_year", "fleet_number", "fleet_code", "reg", "code"
            )
        else:
            # Apply custom sorting if specified
            sort_option = request.GET.get("sort", "")
            if sort_option:
                if sort_option == "fleet_number_asc":
                    vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")
                elif sort_option == "fleet_number_desc":
                    vehicles = vehicles.order_by("-fleet_number", "-fleet_code", "-reg", "-code")
                elif sort_option == "type_asc":
                    vehicles = vehicles.order_by("vehicle_type__name", "fleet_number", "fleet_code", "reg", "code")
                elif sort_option == "type_desc":
                    vehicles = vehicles.order_by("-vehicle_type__name", "-fleet_number", "-fleet_code", "-reg", "-code")
                elif sort_option == "age_asc":
                    # Oldest first - sort by year_of_manufacture ascending
                    vehicles = vehicles.order_by("year_of_manufacture", "fleet_number", "fleet_code", "reg", "code")
                elif sort_option == "age_desc":
                    # Newest first - sort by year_of_manufacture descending
                    vehicles = vehicles.order_by("-year_of_manufacture", "-fleet_number", "-fleet_code", "-reg", "-code")
                else:
                    # Default sorting
                    has_fleet_numbers = operator.vehicle_set.filter(fleet_number__isnull=False).exists()
                    if has_fleet_numbers:
                        vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")
                    else:
                        vehicles = vehicles.order_by("vehicle_type__name", "fleet_code", "reg", "code")
            else:
                # Check if the operator has any fleet_number values set
                has_fleet_numbers = operator.vehicle_set.filter(fleet_number__isnull=False).exists()

                if has_fleet_numbers:
                    vehicles = vehicles.order_by("fleet_number", "fleet_code", "reg", "code")
                else:
                    # No fleet numbers - sort by vehicle type
                    vehicles = vehicles.order_by("vehicle_type__name", "fleet_code", "reg", "code")
        completion_summary = get_completion_summary_for_queryset(vehicle_ids, request.user)

    if group_slug:
        all_operators = list(active_operators) + list(ceased_operators)
        for operator in active_operators:
            if not operator.logo or not operator.logo.name:
                logging.warning(f"Operator {operator.name} ({operator.noc}) has no logo")
        all_have_logos = all(operator.logo and operator.logo.name for operator in active_operators) if active_operators else False
        context = {
            "object": group,
            "active_operators": active_operators,
            "ceased_operators": ceased_operators,
            "breadcrumb": [group.organisation, group] if group.organisation_id else [group],
            "all_operators_have_logos": all_have_logos,
            "all_operators": all_operators,
        }
    else:
        context = {
            "object": operator,
            "breadcrumb": [operator.group or operator.region, operator],
            "depots_count": len(get_operator_depots(operator)),
            "liveries_count": operator.vehicle_set.filter(
                **current_fleet_filter(withdrawn=False, preserved=False)
            )
            .exclude(livery__isnull=True)
            .values("livery_id")
            .distinct()
            .count(),
            "services_count": operator.service_set.filter(current=True).count(),
            "social_links": get_operator_social_links(operator),
            "historical": historical,
            "active_operator_tab": active_operator_tab,
            "show_completion": show_completion,
            "completion_summary": completion_summary,
            "mass_log_mode": mass_log_mode,
            "show_dvla_status": show_dvla_status,
            "is_pinned": False,
            "selected_garage": selected_garage if not historical else None,
            "selected_livery": selected_livery if not historical else None,
            "selected_vehicle_type": selected_vehicle_type if not historical else None,
            "logged_filter": logged_filter if not historical else None,
            "sort_option": sort_option if not historical else None,
            "available_liveries": Livery.objects.filter(
                vehicle__operator=operator
            ).distinct().order_by('name') if not historical else Livery.objects.none(),
            "available_vehicle_types": VehicleType.objects.filter(
                vehicle__operator=operator
            ).distinct().order_by('name') if not historical else VehicleType.objects.none(),
            "available_garages": Garage.objects.filter(
                vehicle__operator=operator
            ).distinct().order_by('name') if not historical else Garage.objects.none(),
        }

    if request.user.is_authenticated:
        try:
            context["is_pinned"] = PinnedOperator.objects.filter(
                user=request.user, operator=operator
            ).exists()
        except Exception:
            context["is_pinned"] = False

    vehicles = apply_vehicle_schema_compat(vehicles)

    if not vehicles.exists():
        object_label = "group" if group else "operator"
        context = {
            **context,
            "parent": group,
            "vehicles": [],
            "columns": (),
            "branding_column": False,
            "name_column": False,
            "notes_column": False,
            "garage_column": False,
            "features_column": False,
            "ratings_column": False,
            "map": False,
            "historical": historical,
            "error_message": f"No vehicles are currently available for this {object_label}.",
        }
        if not group and active_operator_tab == "depots":
            context["depots"] = get_operator_depots(operator)
            context["depot_map_html"] = build_depot_map_html(
                serialize_depot_map_points(context["depots"])
            )
        return render(request, "operator_vehicles.html", context)

    vehicles = sorted(vehicles, key=get_vehicle_order)
    if not group and operator.noc in settings.ALLOW_VEHICLE_NOTES_OPERATORS:
        vehicles = sorted(vehicles, key=lambda v: v.notes)

    if group:
        paginator = Paginator(vehicles, 1000)
        page = request.GET.get("page")
        vehicles = paginator.get_page(page)

        for v in vehicles:
            v.operator = operators[v.operator_id]
            v.operator_name = v.operator.name.removeprefix(f"{group} ")

        context["paginator"] = paginator
    else:
        paginator = None

    if group:
        columns = get_operator_vehicle_columns(None, vehicles)
    else:
        columns = get_operator_vehicle_columns(operator, vehicles)
    for vehicle in vehicles:
        vehicle.column_values = [get_vehicle_column_value(vehicle, column) for column in columns]
    context["columns"] = columns

    if not group:
        now = timezone.localtime()

        # midnight or 12 hours ago, whichever happened first
        if now.hour >= 12:
            today = now - datetime.timedelta(hours=now.hour, minutes=now.minute)
            today = today.replace(second=0, microsecond=0)
        else:
            today = now - datetime.timedelta(hours=12)

        context["today"] = today

        for vehicle in vehicles:
            if vehicle.latest_journey:
                when = vehicle.latest_journey.datetime
                vehicle.last_seen = {
                    "service": vehicle.latest_journey.route_name,
                    "when": when,
                    "today": when >= today,
                }

        context["map"] = any(
            hasattr(vehicle, "last_seen") and vehicle.last_seen["today"]
            for vehicle in vehicles
        )
        context["last_tracked_column"] = any(
            hasattr(vehicle, "last_seen") for vehicle in vehicles
        )

    for vehicle in vehicles:
        review_ratings = [review.rating for review in vehicle.reviews.all()]
        vehicle.review_count = len(review_ratings)
        vehicle.average_rating = (
            sum(review_ratings) / len(review_ratings) if review_ratings else 0
        )
        vehicle.row_class = vehicle.get_fleet_row_class()

    if not group:
        context["features_column"] = any(vehicle.feature_names for vehicle in vehicles)
        context["ratings_column"] = any(vehicle.review_count for vehicle in vehicles)
        context["has_dvla_status_data"] = any(
            vehicle.dvla_tax_status or vehicle.dvla_euro_status for vehicle in vehicles
        )
        if active_operator_tab == "depots":
            context["depots"] = get_operator_depots(operator)
            context["depot_map_html"] = build_depot_map_html(
                serialize_depot_map_points(context["depots"])
            )
        else:
            context["depots"] = []
            context["depot_map_html"] = ""

    garage_names = set(
        vehicle.garage_name for vehicle in vehicles if vehicle.garage_name
    )

    # Timeline feature: check if all vehicles have joined_fleet and (left_fleet OR not withdrawn)
    timeline_data = None
    if not group and not historical and vehicles:
        # Check if joined_fleet column exists
        if "joined_fleet" in _vehicle_db_columns() and "left_fleet" in _vehicle_db_columns():
            all_have_joined = all(
                getattr(vehicle, "joined_fleet", None) for vehicle in vehicles
            )
            all_have_left_or_not_withdrawn = all(
                getattr(vehicle, "left_fleet", None) or not getattr(vehicle, "withdrawn", False)
                for vehicle in vehicles
            )
            
            if all_have_joined and all_have_left_or_not_withdrawn:
                # Parse dates and find range
                dates = []
                for vehicle in vehicles:
                    joined = getattr(vehicle, "joined_fleet", None)
                    left = getattr(vehicle, "left_fleet", None)
                    if joined:
                        try:
                            joined_date = datetime.datetime.strptime(joined, "%m-%Y")
                            dates.append(("joined", joined_date, vehicle))
                        except ValueError:
                            pass
                    if left:
                        try:
                            left_date = datetime.datetime.strptime(left, "%m-%Y")
                            dates.append(("left", left_date, vehicle))
                        except ValueError:
                            pass
                
                if dates:
                    dates.sort(key=lambda x: x[1])
                    earliest_date = dates[0][1]
                    latest_date = max(d[1] for d in dates)
                    
                    # Create timeline markers (every 6 months)
                    timeline_markers = []
                    current = earliest_date
                    while current <= latest_date:
                        timeline_markers.append(current.strftime("%m-%Y"))
                        current = datetime.datetime(
                            current.year + (current.month + 5) // 12,
                            (current.month + 5) % 12 + 1,
                            1
                        )
                    
                    timeline_data = {
                        "earliest": earliest_date.strftime("%m-%Y"),
                        "latest": latest_date.strftime("%m-%Y"),
                        "markers": timeline_markers,
                        "current": latest_date.strftime("%m-%Y"),  # Default to latest
                    }

    context = {
        **context,
        "parent": group,
        "vehicles": vehicles,
        "branding_column": any(vehicle.branding for vehicle in vehicles),
        "name_column": any(vehicle.name for vehicle in vehicles),
        "notes_column": any(
            vehicle.notes and not vehicle.is_spare_ticket_machine()
            for vehicle in vehicles
        ),
        "garage_column": len(garage_names) > 1,
        "ratings_column": context.get(
            "ratings_column",
            any(getattr(vehicle, "review_count", 0) for vehicle in vehicles),
        ),
        "last_tracked_column": context.get("last_tracked_column", False),
        "selected_garage": selected_garage if not group and not historical else None,
        "historical_year_cards": historical_year_cards,
        "selected_historical_year": selected_historical_year,
        "historical_year_column": historical
        and any(getattr(vehicle, "historical_fleet_year", None) for vehicle in vehicles),
        "historical": historical,
        "show_completion": show_completion,
        "completion_summary": completion_summary,
        "mass_log_mode": mass_log_mode,
        "show_dvla_status": show_dvla_status,
        "has_dvla_status_data": context.get("has_dvla_status_data", False),
        "timeline_data": timeline_data,
        "view_mode": view_mode,
    }

    # When viewing historical fleets without a specific year selected, show only the year list
    if historical and not selected_historical_year and not group:
        context["historical_years"] = historical_year_cards
        return render(request, "operator_vehicles_historical.html", context)

    return render(request, "operator_vehicles.html", context)


@login_required
@require_http_methods(["GET"])
def export_fleet_basic(request, slug=None, group_slug=None):
    """Export fleet in basic human-readable format"""
    if group_slug:
        group = get_object_or_404(OperatorGroup, slug=group_slug)
        vehicles = Vehicle.objects.filter(
            operator__group=group,
            operator__ceased_operations_on__isnull=True,
            **current_fleet_filter(),
        ).select_related("operator", "vehicle_type", "livery").prefetch_related("features")
        operator = None  # For group exports, we'll use first operator's info
        filename = f"{group.slug}-fleet-basic.xlsx"
    else:
        operator = get_object_or_404(Operator.objects.select_related("organisation", "group", "government_authority"), slug=slug.lower())
        vehicles = operator.vehicle_set.filter(**current_fleet_filter()).select_related("operator", "vehicle_type", "livery").prefetch_related("features")
        filename = f"{operator.slug}-fleet-basic.xlsx"
    
    if "withdrawn" not in request.GET:
        vehicles = vehicles.filter(**current_fleet_filter(withdrawn=False))
    
    workbook = build_basic_fleet_workbook(operator, vehicles, advanced=False)
    response = HttpResponse(
        workbook_bytes(workbook),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_http_methods(["GET"])
def export_fleet_advanced(request, slug=None, group_slug=None):
    """Export fleet in advanced format with additional fields"""
    if not request.user.is_authenticated:
        raise PermissionDenied
    
    # Check if user has advanced mode enabled
    if not request.user.advanced_mode:
        raise PermissionDenied
    
    if group_slug:
        group = get_object_or_404(OperatorGroup, slug=group_slug)
        vehicles = Vehicle.objects.filter(
            operator__group=group,
            operator__ceased_operations_on__isnull=True,
            **current_fleet_filter(),
        ).select_related("operator", "vehicle_type", "livery").prefetch_related("features")
        operator = None
        filename = f"{group.slug}-fleet-advanced.xlsx"
    else:
        operator = get_object_or_404(Operator.objects.select_related("organisation", "group", "government_authority"), slug=slug.lower())
        vehicles = operator.vehicle_set.filter(**current_fleet_filter()).select_related("operator", "vehicle_type", "livery").prefetch_related("features")
        filename = f"{operator.slug}-fleet-advanced.xlsx"
    
    if "withdrawn" not in request.GET:
        vehicles = vehicles.filter(**current_fleet_filter(withdrawn=False))
    
    workbook = build_basic_fleet_workbook(operator, vehicles, advanced=True)
    response = HttpResponse(
        workbook_bytes(workbook),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_http_methods(["GET"])
def fleet_history_calendar(request, slug):
    """Fleet History calendar view showing months/years"""
    operator = get_object_or_404(Operator.objects.select_related("region"), slug=slug)
    
    # Get all historical vehicles for this operator
    historical_vehicles = HistoricalVehicle.objects.filter(operator=operator)
    
    # Find the earliest joined_fleet_date
    earliest_date = historical_vehicles.filter(joined_fleet_date__isnull=False).order_by('joined_fleet_date').first()
    
    if not earliest_date:
        # No historical vehicles with dates yet
        return render(request, "fleet_history_calendar.html", {
            "object": operator,
            "breadcrumb": [operator.group or operator.region, operator],
            "calendar_months": [],
            "no_data": True,
        })
    
    start_date = earliest_date.joined_fleet_date
    end_date = timezone.now().date()
    
    # Generate list of months from start_date to end_date
    calendar_months = []
    current = datetime.date(start_date.year, start_date.month, 1)
    
    while current <= end_date:
        month_end = datetime.date(
            current.year + (current.month // 12),
            (current.month % 12) + 1,
            1
        ) - datetime.timedelta(days=1)
        
        # Count vehicles present in this month
        vehicles_in_month = historical_vehicles.filter(
            joined_fleet_date__lte=month_end
        ).filter(
            Q(left_fleet_date__isnull=True) | Q(left_fleet_date__gte=current)
        ).count()
        
        calendar_months.append({
            'year': current.year,
            'month': current.month,
            'month_name': current.strftime("%B"),
            'vehicle_count': vehicles_in_month,
        })
        
        # Move to next month
        current = datetime.date(
            current.year + (current.month // 12),
            (current.month % 12) + 1,
            1
        )
    
    # Reverse to show most recent first
    calendar_months.reverse()
    
    return render(request, "fleet_history_calendar.html", {
        "object": operator,
        "breadcrumb": [operator.group or operator.region, operator],
        "calendar_months": calendar_months,
        "no_data": False,
    })


@require_http_methods(["GET"])
def fleet_history_month(request, slug, year, month):
    """Fleet History for a specific month"""
    operator = get_object_or_404(Operator.objects.select_related("region"), slug=slug)
    
    # Parse the date
    try:
        month_start = datetime.date(year, month, 1)
        month_end = datetime.date(
            year + (month // 12),
            (month % 12) + 1,
            1
        ) - datetime.timedelta(days=1)
    except ValueError:
        raise Http404("Invalid date")
    
    # Get vehicles present in this month
    vehicles = HistoricalVehicle.objects.filter(
        operator=operator,
        joined_fleet_date__lte=month_end
    ).filter(
        Q(left_fleet_date__isnull=True) | Q(left_fleet_date__gte=month_start)
    ).select_related("vehicle_type", "livery", "garage")
    
    # Annotate with features
    vehicles = vehicles.annotate(
        feature_names=features_string_agg,
        accessibility_names=accessibility_string_agg,
        livery_name=Case(When(livery__show_name=True, then="livery__name")),
        vehicle_type_name=F("vehicle_type__name"),
        garage_name=Case(
            When(garage__name="", then="garage__code"),
            default="garage__name",
        ),
    )
    
    vehicles = annotate_logged_state(vehicles, request.user)
    vehicles = annotate_photographed_state(vehicles, request.user)
    
    vehicles = vehicles.prefetch_related(
        Prefetch(
            "reviews",
            queryset=VehicleReview.objects.filter(
                status=VehicleReview.Status.PUBLISHED
            ),
        )
    )
    
    vehicles = list(vehicles)
    vehicles = sorted(vehicles, key=get_vehicle_order)
    
    # Get columns
    columns = get_operator_vehicle_columns(operator, vehicles)
    for vehicle in vehicles:
        vehicle.column_values = [get_vehicle_column_value(vehicle, column) for column in columns]
    
    # Calculate completion summary
    vehicle_ids = [v.id for v in vehicles]
    completion_summary = get_completion_summary_for_queryset(vehicle_ids, request.user)
    
    return render(request, "operator_vehicles.html", {
        "object": operator,
        "breadcrumb": [operator.group or operator.region, operator],
        "vehicles": vehicles,
        "columns": columns,
        "branding_column": any(vehicle.branding for vehicle in vehicles),
        "name_column": any(vehicle.name for vehicle in vehicles),
        "notes_column": any(vehicle.notes for vehicle in vehicles),
        "garage_column": any(vehicle.garage_name for vehicle in vehicles),
        "features_column": any(vehicle.feature_names for vehicle in vehicles),
        "ratings_column": any(getattr(vehicle, 'review_count', 0) for vehicle in vehicles),
        "historical": True,
        "active_operator_tab": "fleet_history",
        "show_completion": request.user.is_authenticated,
        "completion_summary": completion_summary,
        "selected_month": month_start.strftime("%B %Y"),
        "fleet_history_mode": True,
    })


@require_safe
def operator_map(request, slug):
    operator = get_object_or_404(Operator.objects.select_related("region"), slug=slug)

    return render(
        request,
        "operator_map.html",
        {
            "object": operator,
            "operator": operator,
            "breadcrumb": [operator.region, operator],
        },
    )


def operator_debug(request, slug):
    operator = get_object_or_404(Operator, slug=slug)

    services = operator.service_set.filter(current=True)

    services = services.annotate(
        current_routes=Exists(
            Route.objects.filter(
                Q(end_date=None) | Q(end_date__gte=Now()), service=OuterRef("id")
            )
        )
    )

    pipe = redis_client.pipeline(transaction=False)
    for service in services:
        pipe.exists(f"service{service.id}vehicles")
    tracking = pipe.execute()

    for service, service_tracking in zip(services, tracking):
        service.last_tracked = service_tracking

    return render(
        request,
        "operator_debug.html",
        {
            "object": operator,
            "breadcrumb": [operator],
            "services": services,
        },
    )


@require_http_methods(["GET"])
def bus_group_detail(request, slug):
    bus_group = get_object_or_404(BusGroup, slug=slug)

    return render(
        request,
        "vehicles/bus_group_detail.html",
        {
            "object": bus_group,
            "page_theme": bus_group,
        },
    )


@require_safe
def events(request):
    search_query = request.GET.get("search", "").strip()
    
    bus_groups = BusGroup.objects.filter(
        event_date__isnull=False
    ).order_by("event_date", "event_end_date", "title")
    
    if search_query:
        bus_groups = bus_groups.filter(title__icontains=search_query)
    
    return render(
        request,
        "vehicles/events.html",
        {
            "bus_groups": bus_groups,
            "search_query": search_query,
        },
    )





def respond_conditionally(request, response):
    if not response.has_header("ETag"):
        set_response_etag(response)

    etag = response.get("ETag")
    return get_conditional_response(
        request,
        etag=etag,
        response=response,
    )


@require_safe
def vehicles_json(request) -> JsonResponse:
    try:
        items = get_bustimes_vehicle_items(request)
    except (requests.RequestException, ValueError) as exc:
        logging.warning("Could not fetch Bustimes vehicles.json: %s", exc)
        return JsonResponse([], safe=False, status=502)

    locations = normalize_bustimes_vehicle_items(items)

    trip = request.GET.get("trip")
    if trip:
        try:
            trip = int(trip)
        except ValueError:
            raise BadRequest
        locations = [
            item
            for item in locations
            if item.get("trip_id") == trip or item.get("trip_id") == str(trip)
        ]

    if len(locations) == 1 or trip:
        for item in locations:
            if "progress" not in item and "trip_id" in item:
                add_progress_and_delay(item)

    # Add source metadata to all vehicles
    for item in locations:
        item["source"] = "live"

    response = JsonResponse(locations, safe=False)
    # Disable caching to ensure fresh data
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'

    return response


def get_dates(vehicle=None, service=None):
    if not vehicle:
        # the database query for a service is too slow
        return

    journeys = vehicle.vehiclejourney_set

    dates = (
        journeys.filter(date__isnull=False)
        .values_list("date", flat=True)
        .order_by("date")
        .distinct()
    )

    return list(dates)


def journeys_list(request, journeys, service=None, vehicle=None) -> dict:
    """list of VehicleJourneys (and dates) for a service or vehicle"""

    if vehicle and vehicle.latest_journey:
        last_date = vehicle.latest_journey.date
        dates = cache.get_or_set(
            f"vehicle{vehicle.id}dates{last_date}",
            partial(get_dates, vehicle=vehicle),
            timeout=86400,
        )
    else:
        dates = get_dates(vehicle=vehicle, service=service)

    context = {}

    form = forms.DateForm(request.GET)
    if form.is_valid():
        date = form.cleaned_data["date"]
    else:
        date = None

    if not date and dates is None:
        if vehicle and vehicle.latest_journey:
            date = last_date
        else:
            date = journeys.aggregate(max_date=Max("date"))["max_date"]

    if dates:
        context["dates"] = dates
        if not date:
            date = context["dates"][-1]

    if date:
        context["date"] = date

        journeys = journeys.filter(date=date).select_related("trip").order_by("id")

        if dates:
            if date not in dates:
                dates.append(date)
                dates.sort()

        context["journeys"] = journeys

    elif service:
        raise Http404

    if not date or not journeys:
        return context

    context["journeys"] = journeys = list(journeys)

    # annotate journeys with whether each one has some location history in redis
    # (in order to show the "Map" link or not)
    if redis_client:
        try:
            pipe = redis_client.pipeline(transaction=False)
            for journey in journeys:
                pipe.exists(journey.get_redis_key())

            locations = pipe.execute()
        except (ConnectionError, AttributeError):
            pass
        else:
            for journey, location in zip(journeys, locations):
                journey.locations = bool(location)

    # "Track this bus" button
    if vehicle and vehicle.latest_journey_id:
        if redis_client and redis_client.get(f"vehicle{vehicle.id}"):
            context["tracking"] = f"#journeys/{vehicle.latest_journey_id}"

        # predict next workings
        if vehicle.latest_journey_id == journeys[-1].pk:
            trips = [journey.trip for journey in journeys if journey.trip]
            if trips:
                last_trip = trips[-1]
                if last_trip.block and all(
                    trip.block == last_trip.block for trip in trips[-3:-1]
                ):
                    context["predictions"] = (
                        get_other_trips_in_block(
                            last_trip,
                            date,
                        )
                        .filter(
                            start__gte=last_trip.end,
                        )
                        .annotate(
                            destination_name=Coalesce(
                                "headsign",
                                "destination__locality__name",
                                "destination__common_name",
                            ),
                            line_name=F("route__line_name"),
                        )
                    )
                    for a, b in pairwise(context["predictions"]):
                        if a.end > b.start:
                            del context["predictions"]
                            break

    return context


@require_safe
def service_vehicles_history(request, slug=None, noc=None, line_name=None):
    if slug:
        services = Service.objects.with_line_names()
        try:
            service: Service = services.get(slug=slug)
        except Service.DoesNotExist:
            service = get_object_or_404(
                services,
                servicecode__scheme__in=(BUSTIMES_SLUG_SCHEME, "slug"),
                servicecode__code=slug,
            )
        operator = service.operator.first()
        journeys = service.vehiclejourney_set
    else:
        service = None
        operator = get_object_or_404(Operator, noc=noc)
        journeys = VehicleJourney.objects.filter(
            service=None, route_name=line_name, vehicle__operator=operator
        )

    context = journeys_list(
        request, journeys.select_related("vehicle"), service=service
    )

    if not context:
        raise Http404

    if service:
        context["garages"] = Garage.objects.filter(
            trip__route__service=service
        ).distinct()
        context["title"] = f"Vehicles \u2013 {service.get_line_name_and_brand()}"
    else:
        context["title"] = f"Vehicles \u2013 {line_name}"

    return render(
        request,
        "vehicles/vehicle_detail.html",
        {
            **context,
            "breadcrumb": [operator, service],
            "object": service or line_name,
        },
    )


class VehicleDetailView(DetailView):
    model = Vehicle

    def get_queryset(self):
        detail_related = ["operator", "operator__region", "vehicle_type", "livery"]
        if "latest_journey_id" in _vehicle_db_columns():
            detail_related.append("latest_journey")
        return apply_vehicle_schema_compat(
            self.model.objects.select_related(*detail_related).prefetch_related(
                "features", "photo_set"
            )
        )

    def get_object(self, **kwargs):
        try:
            return super().get_object(**kwargs)
        except Http404:
            if slug := self.kwargs.get("slug"):
                return get_object_or_404(
                    self.get_queryset(),
                    vehiclecode__code=slug,
                    vehiclecode__scheme__in=(BUSTIMES_SLUG_SCHEME, "slug"),
                )
            raise

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        journeys = self.object.vehiclejourney_set.select_related("service")
        journeys = journeys.annotate(
            line_name=Coalesce("trip__route__line_name", "route_name")
        )

        context = {
            **context,
            **journeys_list(self.request, journeys, vehicle=self.object),
        }
        del journeys

        if self.object.reg:
            # for search engine purposes, use reg without space:
            context["title"] = self.object.reg
            if self.object.fleet_code:
                context["title"] = self.object.fleet_code + " - " + context["title"]
        else:
            context["title"] = str(self.object)

        if "journeys" in context:
            garages = set(
                journey.trip.garage_id
                for journey in context["journeys"]
                if journey.trip and journey.trip.garage_id
            )
            if len(garages) == 1:
                context["garage"] = Garage.objects.get(id=garages.pop())

        if self.object.withdrawn and self.object.reg and not self.object.historical_fleet_id:
            context["potential_duplicates"] = apply_vehicle_schema_compat(
                Vehicle.objects.filter(~Q(id=self.object.id), reg__iexact=self.object.reg)
            )

        if self.object.operator:
            context["breadcrumb"] = [
                self.object.operator,
                Vehicles(vehicle=self.object),
            ]

            context["previous"] = self.object.get_previous()
            context["next"] = self.object.get_next()

        if self.object.name:
            context["name_page"] = VehicleNamePage.objects.filter(
                name__iexact=self.object.name
            ).first()

        context["reviews"] = self.object.reviews.filter(
            status=VehicleReview.Status.PUBLISHED
        ).select_related("user").order_by("-updated_at", "-created_at")
        context["average_rating"] = (
            context["reviews"].aggregate(value=Avg("rating"))["value"] or 0
        )
        context["review_count"] = context["reviews"].count()
        context["review_blocked"] = bool(
            self.request.user.is_authenticated
            and getattr(self.request.user, "blocked_from_reviews", False)
        )
        if self.request.user.is_authenticated and not context["review_blocked"]:
            context["review_form"] = forms.VehicleReviewForm()

        if self.request.user.has_perm("photos.add_photo"):
            context["photo_form"] = PhotoForm()
        elif getattr(self.request.user, "trusted", False):
            context["photo_form"] = PhotoForm()
        if self.request.user.is_authenticated:
            context["can_log_vehicle"] = True
            context["vehicle_logged"] = has_vehicle_been_logged(
                self.request.user, self.object
            )
        if getattr(self.request.user, "is_driver", False):
            context["can_drive_log"] = True
            context["vehicle_driven"] = has_vehicle_been_driven(
                self.request.user, self.object
            )
        if self.request.user.is_authenticated:
            context["can_photo_log"] = True
            photo_log = FleetPhotoLog.objects.filter(
                user=self.request.user, vehicle=self.object
            ).first()
            context["vehicle_photographed"] = photo_log is not None
            context["photo_log_quantity"] = photo_log.quantity if photo_log else 0
        total_photos = FleetPhotoLog.objects.filter(vehicle=self.object).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        context["total_photo_count"] = total_photos

        # Check if advanced fields should be shown
        show_advanced = self.request.GET.get("advanced") == "1"
        if self.request.user.is_authenticated and getattr(self.request.user, "view_advanced", False):
            show_advanced = True
        
        if show_advanced:
            from .models import AdvancedField
            advanced_fields = AdvancedField.objects.all().order_by("display_order", "name")
            context["advanced_fields"] = advanced_fields
            context["show_advanced"] = True

        # Get previous operators from vehicle field or vehicle history events
        previous_operators = []
        if self.object.previous_operators:
            # Use the direct previous_operators field
            for op_data in self.object.previous_operators:
                try:
                    from busstops.models import Operator
                    operator = Operator.objects.get(id=op_data['operator_id'])
                    previous_operators.append({
                        'operator': operator,
                        'joined_fleet': op_data.get('joined_fleet'),
                    })
                except (Operator.DoesNotExist, KeyError):
                    pass
        else:
            # Fall back to vehicle history events
            try:
                from vehicle_history.models import VehicleHistoryEvent, EventType
                transfer_events = VehicleHistoryEvent.objects.filter(
                    vehicle=self.object,
                    event_type=EventType.TRANSFER,
                ).order_by('-event_date', '-created_at')

                for event in transfer_events:
                    metadata = event.metadata or {}
                    if 'from_operator' in metadata:
                        try:
                            from busstops.models import Operator
                            operator = Operator.objects.get(id=metadata['from_operator'])
                            previous_operators.append({
                                'operator': operator,
                                'joined_fleet': event.event_date.strftime('%m-%Y') if event.event_date else None,
                            })
                        except Operator.DoesNotExist:
                            pass
            except Exception:
                # If vehicle_history app is not available or has issues, skip
                pass

        context['previous_operators'] = previous_operators

        return context

    def render_to_response(self, context):
        response = super().render_to_response(context)

        if self.object.withdrawn and "potential_duplicates" in context:
            if not all(
                vehicle.withdrawn for vehicle in context["potential_duplicates"]
            ):
                response.status_code = HTTPStatus.NOT_FOUND

        return response

    def post(self, *args, **kwargs):
        vehicle = self.get_object()
        if (
            self.request.user.is_authenticated
            and "toggle_ride_log" in self.request.POST
        ):
            should_log = self.request.POST.get("toggle_ride_log") == "1"
            _, changed = set_ride_log_state(
                self.request.user,
                vehicle,
                logged=should_log,
            )
            if should_log:
                if changed:
                    messages.success(self.request, "Vehicle marked as logged.")
                else:
                    messages.info(self.request, "Vehicle was already logged.")
            else:
                if changed:
                    messages.success(self.request, "Vehicle log removed.")
                else:
                    messages.info(self.request, "Vehicle was not logged.")
            return self.get(*args, **kwargs)
        if (
            self.request.user.is_authenticated
            and getattr(self.request.user, "is_driver", False)
            and "toggle_driving_log" in self.request.POST
        ):
            should_log = self.request.POST.get("toggle_driving_log") == "1"
            if should_log:
                _, changed = create_driving_log(self.request.user, vehicle)
                if changed:
                    messages.success(self.request, "Vehicle marked as driven.")
                else:
                    messages.info(self.request, "Vehicle was already marked as driven.")
            else:
                from fleet.models import FleetDrivingLog
                deleted, _ = FleetDrivingLog.objects.filter(
                    user=self.request.user, vehicle=vehicle
                ).delete()
                if deleted:
                    messages.success(self.request, "Driving log removed.")
                else:
                    messages.info(self.request, "Vehicle was not marked as driven.")
            return self.get(*args, **kwargs)
        if (
            self.request.user.is_authenticated
            and "log_photo" in self.request.POST
        ):
            photo_log, created = FleetPhotoLog.objects.get_or_create(
                user=self.request.user, vehicle=vehicle
            )
            if created:
                photo_log.quantity = 1
                photo_log.save()
                messages.success(self.request, "Photo logged.")
            else:
                photo_log.quantity += 1
                photo_log.save(update_fields=["quantity"])
                messages.success(self.request, f"Photo logged (total: {photo_log.quantity}).")
            return self.get(*args, **kwargs)
        if (
            self.request.user.is_authenticated
            and "suggest_photo" in self.request.POST
        ):
            from busstops.data_changes import record_pending_change
            from django.http import JsonResponse
            
            flickr_url = self.request.POST.get("photo_url", "")
            if not flickr_url or "flickr.com" not in flickr_url.lower():
                if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({"success": False, "error": "Please enter a valid Flickr URL"})
                else:
                    messages.error(self.request, "Please enter a valid Flickr URL")
                    return self.get(*args, **kwargs)
            
            # Create a pending change for the photo suggestion
            record_pending_change(
                source="photo_suggestion",
                instance=vehicle,
                operation="add_photo",
                changes={"flickr_url": {"to": flickr_url}},
                payload={
                    "flickr_url": flickr_url,
                    "requested_by_id": self.request.user.id,
                    "requested_by_label": str(self.request.user),
                    "requested_title": f"Photo for {vehicle}",
                    "summary": f"Photo suggestion by {self.request.user.username}",
                },
                reason=f"Photo suggestion by {self.request.user.username}"
            )
            
            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({"success": True})
            else:
                messages.success(self.request, "Photo suggestion submitted for approval!")
                return self.get(*args, **kwargs)
        if self.request.user.is_authenticated and (
            "rating" in self.request.POST or "message" in self.request.POST
        ):
            if getattr(self.request.user, "blocked_from_reviews", False):
                raise PermissionDenied("You are blocked from submitting reviews.")
            form = forms.VehicleReviewForm(self.request.POST)
            if form.is_valid():
                review = form.save(commit=False)
                review.vehicle = vehicle
                review.user = self.request.user
                flagged_terms = find_blocked_review_phrases(review.message)
                if flagged_terms:
                    review.status = VehicleReview.Status.PENDING
                    review.flagged_terms = flagged_terms
                    review.moderation_notes = (
                        "Automatically held for moderation due to blocked phrases."
                    )
                review.save()
            else:
                self.object = vehicle
                context = self.get_context_data(object=vehicle)
                context["review_form"] = form
                return self.render_to_response(context)
        elif self.request.user.is_authenticated and "report_review_id" in self.request.POST:
            review = get_object_or_404(
                VehicleReview,
                pk=self.request.POST.get("report_review_id"),
                vehicle=vehicle,
            )
            form = forms.VehicleReviewReportForm(self.request.POST)
            if form.is_valid():
                VehicleReviewReport.objects.get_or_create(
                    review=review,
                    reporter=self.request.user,
                    defaults={"reason": form.cleaned_data["reason"]},
                )
                if review.status == VehicleReview.Status.PUBLISHED:
                    review.status = VehicleReview.Status.PENDING
                    review.moderation_notes = (
                        "Automatically held for moderation after a user report."
                    )
                    review.save(update_fields=["status", "moderation_notes", "updated_at"])
        elif self.request.user.has_perm("vehicles.delete_review") and "delete_review_id" in self.request.POST:
            review = get_object_or_404(
                VehicleReview,
                pk=self.request.POST.get("delete_review_id"),
                vehicle=vehicle,
            )
            review.delete()
        elif self.request.user.has_perm("photos.add_photo"):
            form = PhotoForm(self.request.POST)
            if form.is_valid():
                try:
                    photo = Photo()
                    photo.user = self.request.user
                    photo.flickr_url = form.cleaned_data["flickr_url"]
                    photo.credit = form.cleaned_data.get("credit", "")
                    photo.caption = form.cleaned_data.get("caption", "")
                    photo.author = form.cleaned_data.get("author", "")
                    photo.save()  # This will trigger automatic download
                    photo.vehicles.add(vehicle)
                    messages.success(self.request, "Photo added successfully.")
                except Exception as e:
                    messages.error(self.request, f"Error adding photo: {str(e)}")
        elif getattr(self.request.user, "trusted", False) and "tu_flickr_url" in self.request.POST:
            # Trusted user photo addition
            flickr_url = self.request.POST.get("tu_flickr_url")
            credit = self.request.POST.get("tu_credit", "")
            caption = self.request.POST.get("tu_caption", "")
            
            if not flickr_url:
                messages.error(self.request, "Please provide a Flickr URL.")
                return self.get(*args, **kwargs)
            
            if 'flickr.com' not in flickr_url.lower():
                messages.error(self.request, "Only Flickr URLs are allowed.")
                return self.get(*args, **kwargs)
            
            try:
                photo = Photo()
                photo.user = self.request.user
                photo.flickr_url = flickr_url
                photo.credit = credit
                photo.caption = caption
                photo.save()  # This will trigger automatic download
                photo.vehicles.add(vehicle)
                messages.success(self.request, "Photo added successfully.")
            except Exception as e:
                messages.error(self.request, f"Error adding photo: {str(e)}")
        
        elif self.request.user.is_authenticated and "suggest_photo" in self.request.POST:
            from service_requests.models import Request, RequestCategory
            
            photo_url = self.request.POST.get("photo_url")
            summary = self.request.POST.get("summary")
            
            if not photo_url:
                messages.error(self.request, "Please provide a Flickr URL.")
                return self.get(*args, **kwargs)
            
            if 'flickr.com' not in photo_url.lower():
                messages.error(self.request, "Only Flickr URLs are allowed.")
                return self.get(*args, **kwargs)
            
            if not summary:
                messages.error(self.request, "Please provide a summary.")
                return self.get(*args, **kwargs)
            
            # Create request for photo suggestion
            description = f"Photo suggestion for {vehicle}\n\n"
            description += f"Flickr URL: {photo_url}\n"
            description += f"Summary: {summary}\n"
            description += "Note: Image will be automatically downloaded from Flickr URL when approved."
            
            request_obj = Request.objects.create(
                title=f"Photo suggestion for {vehicle}",
                description=description,
                category=RequestCategory.PHOTO,
                vehicle=vehicle,
                photo_url=photo_url,
                author=self.request.user,
            )
            
            messages.success(self.request, "Photo suggestion submitted for review.")

        return self.get(*args, **kwargs)


class VehicleNamePageDetailView(DetailView):
    model = VehicleNamePage

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehicles = apply_vehicle_schema_compat(
            Vehicle.objects.select_related("operator", "vehicle_type")
            .filter(name__iexact=self.object.name)
            .order_by("operator__name", "fleet_number", "fleet_code", "reg", "code")
        )
        context["vehicles"] = vehicles
        context["breadcrumb"] = [self.object]
        return context



@login_required
def review_moderation(request):
    if not request.user.is_staff:
        raise Http404

    reviews = VehicleReview.objects.select_related(
        "user", "vehicle", "vehicle__operator"
    ).annotate(
        open_report_count=Count(
            "reports",
            filter=Q(reports__status=VehicleReviewReport.Status.OPEN),
            distinct=True,
        )
    )

    status_filter = request.GET.get("status", "queue")
    if status_filter == "published":
        reviews = reviews.filter(status=VehicleReview.Status.PUBLISHED)
    elif status_filter == "hidden":
        reviews = reviews.filter(status=VehicleReview.Status.HIDDEN)
    elif status_filter == "pending":
        reviews = reviews.filter(status=VehicleReview.Status.PENDING)
    elif status_filter == "all":
        pass
    else:
        status_filter = "queue"
        reviews = reviews.filter(
            Q(status=VehicleReview.Status.PENDING)
            | Q(reports__status=VehicleReviewReport.Status.OPEN)
        ).distinct()

    query = request.GET.get("q", "").strip()
    if query:
        reviews = reviews.filter(
            Q(message__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__display_name__icontains=query)
            | Q(vehicle__code__icontains=query)
            | Q(vehicle__fleet_code__icontains=query)
            | Q(vehicle__reg__icontains=query)
        )

    if request.method == "POST":
        review = get_object_or_404(VehicleReview, pk=request.POST.get("review_id"))
        action = request.POST.get("action")
        if action == "publish":
            review.status = VehicleReview.Status.PUBLISHED
            review.save(update_fields=["status", "updated_at"])
            review.reports.filter(status=VehicleReviewReport.Status.OPEN).update(
                status=VehicleReviewReport.Status.DISMISSED
            )
            messages.success(request, "Review published.")
        elif action == "hide":
            review.status = VehicleReview.Status.HIDDEN
            review.save(update_fields=["status", "updated_at"])
            review.reports.filter(status=VehicleReviewReport.Status.OPEN).update(
                status=VehicleReviewReport.Status.RESOLVED
            )
            messages.success(request, "Review hidden.")
        elif action == "delete":
            if not request.user.has_perm("vehicles.delete_review"):
                raise PermissionDenied
            review.delete()
            messages.success(request, "Review deleted.")
        return redirect(request.get_full_path())

    reviews = list(reviews.order_by("-open_report_count", "-updated_at", "-created_at")[:200])
    for review in reviews:
        review.open_reports = review.reports.filter(
            status=VehicleReviewReport.Status.OPEN
        ).select_related("reporter")

    return render(
        request,
        "review_moderation.html",
        {
            "reviews": reviews,
            "status_filter": status_filter,
            "query": query,
            "ad": False,
        },
    )


def check_user(request):
    if request.user.trusted is False:
        raise PermissionDenied

    if (
        not request.user.trusted
        and timezone.now() - request.user.date_joined < datetime.timedelta(hours=1)
        and request.user.vehiclerevision_set.count() > 4
    ):
        raise PermissionDenied(
            "As your account is so new, please wait a bit before editing any more vehicles"
        )


def ensure_vehicle_revision_rules(request, breadcrumb_object):
    form_data = request.POST or None

    if not request.user.has_perm("vehicles.add_vehiclerevision"):
        form = forms.RulesForm(form_data)
        if form.is_valid():
            request.user.user_permissions.add(
                Permission.objects.get(codename="add_vehiclerevision")
            )
            return None
        return render(
            request, "rules.html", {"breadcrumb": [breadcrumb_object], "form": form}
        )

    return form_data


def user_can_edit_operator(request, operator):
    if not operator:
        return True

    return True


def create_request_log(
    *,
    source,
    target_model,
    target_pk,
    target_repr,
    fields,
    changes,
    summary,
    user,
    many_to_many=None,
    status=None,
):
    # Auto-approve vehicle requests from trusted users
    auto_approve = status is None and source == "vehicle_request" and getattr(user, "trusted", False)
    if auto_approve:
        status = DataChangeLog.STATUS_APPLIED
    
    log = DataChangeLog.objects.create(
        source=source,
        target_model=target_model,
        target_pk=target_pk,
        target_repr=target_repr,
        operation="create",
        changes=changes,
        payload={
            "fields": fields,
            "many_to_many": many_to_many or {},
            "requested_by_id": user.id,
            "requested_by_label": str(user),
            "requested_title": target_repr,
            "summary": summary,
        },
        status=status or DataChangeLog.STATUS_PENDING,
        reason=summary,
    )
    
    # If auto-approved, apply the change immediately
    if auto_approve:
        from busstops.data_changes import apply_pending_change
        log = apply_pending_change(log, user=user)
    else:
        # Only send notification for pending requests (not auto-approved ones)
        notify_request_created(
            request_type=REQUEST_SOURCES.get(source, "Request"),
            target_title=target_repr,
            summary=summary,
            user=user,
            changes=changes,
        )
    return log


def can_apply_request_log(user, log):
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if not getattr(user, "trusted", False):
        return False
    return log.source in TRUSTED_REQUEST_APPROVAL_SOURCES


def can_cancel_request_log(user, log):
    if not getattr(user, "is_authenticated", False):
        return False
    requested_by_id = (log.payload or {}).get("requested_by_id")
    if not requested_by_id and log.source == "photo_suggestion":
        # For photo suggestions, extract username from reason and check against current user
        reason = log.reason or ""
        if "by " in reason:
            username = reason.split("by ")[-1].strip()
            return username == user.username
    return str(requested_by_id or "") == str(user.id)


def build_request_change_items(log):
    items = []
    for label, change in (log.changes or {}).items():
        value = change.get("to")
        if not value:
            continue

        item = {
            "label": str(label).replace("_", " ").capitalize(),
            "value": value,
            "is_link": False,
            "preview_css": "",
            "is_code": False,
        }
        lower_label = str(label).lower()
        if lower_label == "image url" or lower_label == "flickr url":
            item["is_link"] = True
        elif lower_label in {"left css", "right css"}:
            item["preview_css"] = str(value)
            item["is_code"] = True
        elif lower_label == "colours":
            try:
                item["preview_css"] = get_css(str(value).split())
            except Exception:
                item["preview_css"] = ""
            item["is_code"] = True
        elif "css" in lower_label:
            item["is_code"] = True
        items.append(SimpleNamespace(**item))
    return items


def get_request_logs_queryset():
    return DataChangeLog.objects.filter(source__in=REQUEST_SOURCES).select_related(
        "approved_by"
    )


def limit_request_logs_visibility(logs, request):
    if request.user.is_authenticated and (request.user.trusted or request.user.is_superuser):
        return logs

    if request.user.is_authenticated:
        requester_id = str(request.user.id)
        visible_ids = []
        for log in logs:
            payload = log.payload or {}
            if log.status == DataChangeLog.STATUS_APPLIED:
                visible_ids.append(log.id)
            elif str(payload.get("requested_by_id") or "") == requester_id:
                visible_ids.append(log.id)
        return logs.filter(id__in=visible_ids)

    return logs.filter(status=DataChangeLog.STATUS_APPLIED)


def filter_request_logs(logs, filter_form, request):
    if not filter_form.is_valid():
        return []

    logs = limit_request_logs_visibility(logs, request)
    show = filter_form.cleaned_data.get("show") or "all"
    if show == "edits":
        return []
    if show not in {"all", "requests"}:
        logs = logs.filter(source=show)

    status = filter_form.cleaned_data["status"]
    if status == "pending":
        logs = logs.filter(status=DataChangeLog.STATUS_PENDING)
    elif status == "disapproved":
        logs = logs.filter(status=DataChangeLog.STATUS_REJECTED)
    else:
        logs = logs.filter(status=DataChangeLog.STATUS_APPLIED)

    user = filter_form.cleaned_data.get("user")
    if user:
        logs = [
            log
            for log in logs
            if str((log.payload or {}).get("requested_by_id") or "") == str(user)
        ]
    else:
        logs = list(logs)

    operator = filter_form.cleaned_data.get("operator")
    if operator:
        operator_value = str(operator).strip().lower()
        filtered = []
        for log in logs:
            payload = log.payload or {}
            fields = payload.get("fields") or {}
            many_to_many = payload.get("many_to_many") or {}
            operator_haystacks = [
                str(fields.get("operator") or ""),
                str(((log.changes or {}).get("operator") or {}).get("to") or ""),
                str(log.target_repr or ""),
            ]
            if any(operator_value in haystack.lower() for haystack in operator_haystacks):
                filtered.append(log)
                continue
            operators = [str(value).lower() for value in many_to_many.get("operator", [])]
            if operator_value in operators:
                filtered.append(log)
        logs = filtered

    vehicle = filter_form.cleaned_data.get("vehicle")
    if vehicle:
        vehicle_id = str(vehicle)
        filtered = []
        for log in logs:
            payload = log.payload or {}
            if log.target_model == "vehicles.vehicle" and str(log.target_pk or "") == vehicle_id:
                filtered.append(log)
                continue

            fields = payload.get("fields") or {}
            requested_vehicle_id = fields.get("vehicle") or fields.get("vehicle_id")
            if str(requested_vehicle_id or "") == vehicle_id:
                filtered.append(log)
        logs = filtered

    query = (filter_form.cleaned_data.get("q") or "").strip().lower()
    if query:
        filtered = []
        for log in logs:
            haystacks = [
                str(log.target_repr or ""),
                str(log.reason or ""),
                str((log.payload or {}).get("summary") or ""),
            ]
            for change in (log.changes or {}).values():
                haystacks.append(str(change.get("to") or ""))
            if any(query in haystack.lower() for haystack in haystacks):
                filtered.append(log)
        logs = filtered

    return logs


@require_safe
def sorn_vehicles(request):
    form = forms.SornVehicleFilterForm(request.GET or None)
    vehicles = apply_vehicle_schema_compat(
        Vehicle.objects.select_related("operator", "vehicle_type", "garage")
    ).filter(dvla_tax_status="SORN")

    if form.is_valid():
        q = (form.cleaned_data.get("q") or "").strip()
        if q:
            compact = q.replace(" ", "").upper()
            vehicles = vehicles.filter(
                Q(code__icontains=q)
                | Q(fleet_code__icontains=q)
                | Q(reg__icontains=compact)
                | Q(name__icontains=q)
                | Q(notes__icontains=q)
            )

        operator_value = (form.cleaned_data.get("operator") or "").strip()
        if operator_value:
            vehicles = vehicles.filter(
                Q(operator__pk__iexact=operator_value)
                | Q(operator__slug__iexact=operator_value)
                | Q(operator__name__icontains=operator_value)
            )

        vehicle_id = form.cleaned_data.get("vehicle")
        if vehicle_id:
            vehicles = vehicles.filter(pk=vehicle_id)

        vehicle_type = form.cleaned_data.get("vehicle_type")
        if vehicle_type:
            vehicles = vehicles.filter(vehicle_type=vehicle_type)

        if not form.cleaned_data.get("include_preserved"):
            vehicles = vehicles.filter(preserved=False)
        if not form.cleaned_data.get("include_withdrawn"):
            vehicles = vehicles.filter(withdrawn=False)
        if not form.cleaned_data.get("include_vor"):
            vehicles = vehicles.filter(vor=False)
        if form.cleaned_data.get("trainer_only"):
            vehicles = vehicles.filter(trainer_vehicle=True)
        if form.cleaned_data.get("fleet_support_only"):
            vehicles = vehicles.filter(fleet_support_vehicle=True)
        if form.cleaned_data.get("awaiting_delivery_only"):
            vehicles = vehicles.filter(awaiting_delivery=True)
        if form.cleaned_data.get("demonstrator_only"):
            vehicles = vehicles.filter(demonstrator=True)

    vehicles = vehicles.annotate(
        vehicle_type_name=F("vehicle_type__name"),
        garage_name=Case(
            When(garage__name="", then="garage__code"),
            default="garage__name",
        ),
    ).order_by("operator__name", "fleet_number", "fleet_code", "reg", "code")

    vehicles = list(vehicles)
    for vehicle in vehicles:
        vehicle.row_class = vehicle.get_fleet_row_class()

    return render(
        request,
        "sorn_vehicles.html",
        {
            "filter_form": form,
            "vehicles": vehicles,
        },
    )


@require_http_methods(["GET", "POST"])
def operator_sorn_untaxed(request):
    from django.core.management import call_command
    from io import StringIO
    import sys

    operator_noc = request.GET.get("operator")
    import_dvla_result = None

    if request.method == "POST" and operator_noc:
        action = request.POST.get("action")
        if action == "import_dvla":
            try:
                output = StringIO()
                call_command(
                    "import_dvla",
                    operator=operator_noc,
                    apply=True,
                    stdout=output,
                    stderr=output
                )
                import_dvla_result = output.getvalue()
            except Exception as e:
                import_dvla_result = f"Error: {str(e)}"

    operators = Operator.objects.order_by("name")
    selected_operator = None
    vehicles = []

    if operator_noc:
        selected_operator = get_object_or_404(Operator, noc=operator_noc)
        vehicles = apply_vehicle_schema_compat(
            Vehicle.objects.select_related("vehicle_type", "livery")
        ).filter(
            operator=selected_operator,
            dvla_tax_status__in=["SORN", "Untaxed", "Not Taxed for on Road Use"],
            withdrawn=False
        )

    # Group vehicles by vehicle type and sort by fleet number within each type
    from collections import defaultdict
    vehicles_by_type = defaultdict(list)
    
    for vehicle in vehicles:
        type_name = vehicle.vehicle_type.name if vehicle.vehicle_type else "Unknown"
        vehicles_by_type[type_name].append(vehicle)
    
    # Sort vehicles within each type by fleet number
    for type_name in vehicles_by_type:
        vehicles_by_type[type_name].sort(
            key=lambda v: (v.fleet_number or float('inf'), v.fleet_code or '', v.reg or '', v.code)
        )
    
    # Sort vehicle types alphabetically
    sorted_types = sorted(vehicles_by_type.items())

    return render(
        request,
        "operator_sorn_untaxed.html",
        {
            "operators": operators,
            "selected_operator": selected_operator,
            "vehicles_by_type": sorted_types,
            "import_dvla_result": import_dvla_result,
        },
    )


def wrap_request_log_for_user(log, user):
    log._request_user = user
    wrapped = wrap_request_log(log)
    try:
        delattr(log, "_request_user")
    except AttributeError:
        pass
    return wrapped


def wrap_vehicle_revision(revision):
    return SimpleNamespace(
        entry_type="vehicle_revision",
        created_at=revision.created_at,
        object=revision,
    )


def wrap_request_log(log):
    requested_by_id = (log.payload or {}).get("requested_by_id")
    # For photo suggestions, get the user from the reason field if requested_by_id is not in payload
    if log.source == "photo_suggestion" and not requested_by_id:
        # Extract username from reason like "Photo suggestion by username"
        reason = log.reason or ""
        if "by " in reason:
            username = reason.split("by ")[-1].strip()
            requested_by_user = User.objects.filter(username=username).first()
            if requested_by_user:
                requested_by_id = str(requested_by_user.id)
                requested_by_label = str(requested_by_user)
            else:
                requested_by_label = username
        else:
            requested_by_label = "Unknown user"
    else:
        requested_by_label = (log.payload or {}).get("requested_by_label") or requested_by_id
        if requested_by_id:
            requested_by_user = User.objects.filter(pk=requested_by_id).first()
            if requested_by_user:
                requested_by_label = str(requested_by_user)
    
    request_type_label = REQUEST_SOURCES.get(log.source, "Request")
    target_model = REQUEST_TARGET_MODELS.get(log.source)
    payload = log.payload or {}
    requested_title = payload.get("requested_title") or log.target_repr
    object_url = ""
    created_object = None

    if log.status == DataChangeLog.STATUS_APPLIED and not target_model and log.target_model:
        try:
            target_model = apps.get_model(log.target_model)
        except LookupError:
            target_model = None

    if log.status == DataChangeLog.STATUS_APPLIED and target_model:
        try:
            # Only attempt lookup if target_pk is a valid numeric ID
            # Synthetic keys like 'create:livery:external:123' will cause ValueError
            if log.target_pk and log.target_pk.isdigit():
                created_object = target_model.objects.get(pk=log.target_pk)
            else:
                created_object = None
        except (target_model.DoesNotExist, ValueError):
            created_object = None
        if created_object and hasattr(created_object, "get_absolute_url"):
            object_url = created_object.get_absolute_url()

    if log.source == "vehicle_request" and not payload.get("requested_title"):
        fields = payload.get("fields") or {}
        operator_id = fields.get("operator")
        operator_label = ((log.changes or {}).get("operator") or {}).get("to") or ""
        code = fields.get("code") or ((log.changes or {}).get("code") or {}).get("to") or ""
        if operator_id and operator_label and code:
            requested_title = f"{operator_label} {code}"
    
    # Handle photo suggestions - they target existing vehicles
    if log.source == "photo_suggestion" and target_model:
        try:
            if log.target_pk and log.target_pk.isdigit():
                created_object = target_model.objects.get(pk=log.target_pk)
                if created_object and hasattr(created_object, "get_absolute_url"):
                    object_url = created_object.get_absolute_url()
                    requested_title = f"Photo for {created_object}"
        except (target_model.DoesNotExist, ValueError):
            pass

    created_title = str(created_object) if created_object else ""

    return SimpleNamespace(
        entry_type="request_log",
        created_at=log.created_at,
        object=SimpleNamespace(
            id=log.id,
            created_at=log.created_at,
            request_type_label=request_type_label,
            title=requested_title,
            created_title=created_title,
            summary=payload.get("summary") or log.reason,
            requested_by_id=requested_by_id,
            requested_by_label=requested_by_label,
            approved_by=log.approved_by,
            pending=log.status == DataChangeLog.STATUS_PENDING,
            disapproved=log.status == DataChangeLog.STATUS_REJECTED,
            approved=log.status == DataChangeLog.STATUS_APPLIED,
            disapproved_reason=log.reason if log.status == DataChangeLog.STATUS_REJECTED else "",
            object_url=object_url,
            changes=build_request_change_items(log),
            can_apply=can_apply_request_log(getattr(log, "_request_user", None), log)
            if hasattr(log, "_request_user")
            else False,
            can_cancel=can_cancel_request_log(getattr(log, "_request_user", None), log)
            if hasattr(log, "_request_user")
            else False,
        ),
    )


@login_required
def dashboard_home(request):
    require_dashboard_access(request)

    model_sections = get_dashboard_model_sections(request)
    
    # Get system health status
    health_status = "unknown"
    try:
        response = requests.get(f"{request.scheme}://{request.get_host()}/up", timeout=5)
        health_status = "healthy" if response.status_code == 200 else "unhealthy"
    except Exception:
        health_status = "unreachable"
    
    # Get vehicle tracking stats from cache
    vehicle_tracking_stats = cache.get("vehicle-tracking-stats", [])
    latest_vehicle_stats = vehicle_tracking_stats[-1] if vehicle_tracking_stats else None
    
    # Get timetable source stats from cache
    timetable_source_stats = cache.get("timetable-source-stats", [])
    latest_source_stats = timetable_source_stats[-1] if timetable_source_stats else None
    
    # Get site usage stats
    from busstops.middleware import get_site_usage_entries
    site_usage = get_site_usage_entries()
    active_users = len([u for u in site_usage.values() if u.get("authenticated", False)])
    active_anonymous = len([u for u in site_usage.values() if not u.get("authenticated", False)])
    
    # Get Redis status
    redis_status = "connected" if redis_client else "disconnected"
    
    # Get database status
    db_status = "unknown"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    # Get Huey queue health
    huey_status = "unknown"
    huey_queue_size = 0
    try:
        import huey
        from django.conf import settings
        
        if hasattr(settings, 'HUEY'):
            huey_instance = settings.HUEY
            if huey_instance:
                # Get queue size
                huey_queue_size = len(huey_instance)
                huey_status = "connected"
            else:
                huey_status = "not configured"
        else:
            huey_status = "not configured"
    except Exception:
        huey_status = "disconnected"
    
    # Build system health section
    system_health = {
        "health_status": health_status,
        "redis_status": redis_status,
        "db_status": db_status,
        "huey_status": huey_status,
        "huey_queue_size": huey_queue_size,
        "active_users": active_users,
        "active_anonymous": active_anonymous,
    }
    
    # Build import status section
    import_status = {}
    if latest_source_stats:
        import_status["sources"] = latest_source_stats.get("sources", {})
        import_status["datetime"] = latest_source_stats.get("datetime")
    else:
        import_status["sources"] = {}
        import_status["datetime"] = None
    
    # Build statistics section
    statistics = {}
    if latest_vehicle_stats:
        statistics["vehicle_journeys"] = latest_vehicle_stats.get("vehicle_journeys", 0)
        statistics["service_vehicle_journeys"] = latest_vehicle_stats.get("service_vehicle_journeys", 0)
        statistics["trip_vehicle_journeys"] = latest_vehicle_stats.get("trip_vehicle_journeys", 0)
        statistics["pending_vehicle_edits"] = latest_vehicle_stats.get("pending_vehicle_edits", 0)
        statistics["datetime"] = latest_vehicle_stats.get("datetime")
    else:
        statistics["vehicle_journeys"] = 0
        statistics["service_vehicle_journeys"] = 0
        statistics["trip_vehicle_journeys"] = 0
        statistics["pending_vehicle_edits"] = 0
        statistics["datetime"] = None
    
    # Get service statistics (cache-backed)
    service_stats = cache.get("service-stats", {})
    if not service_stats:
        try:
            from busstops.models import Service
            service_stats = {
                "total_services": Service.objects.count(),
                "current_services": Service.objects.filter(current=True).count(),
                "datetime": timezone.now(),
            }
            cache.set("service-stats", service_stats, 300)  # Cache for 5 minutes
        except Exception:
            service_stats = {"total_services": 0, "current_services": 0, "datetime": None}
    
    # Get stop statistics (cache-backed)
    stop_stats = cache.get("stop-stats", {})
    if not stop_stats:
        try:
            from busstops.models import StopPoint
            stop_stats = {
                "total_stops": StopPoint.objects.count(),
                "active_stops": StopPoint.objects.filter(active=True).count(),
                "datetime": timezone.now(),
            }
            cache.set("stop-stats", stop_stats, 300)  # Cache for 5 minutes
        except Exception:
            stop_stats = {"total_stops": 0, "active_stops": 0, "datetime": None}
    
    # Get operator statistics (cache-backed)
    operator_stats = cache.get("operator-stats", {})
    if not operator_stats:
        try:
            operator_stats = {
                "total_operators": Operator.objects.count(),
                "operators_with_vehicles": Operator.objects.filter(
                    ceased_operations_on__isnull=True
                ).filter(
                    Exists("vehicle", filter=Q(**current_fleet_filter(withdrawn=False, preserved=False)))
                ).count(),
                "datetime": timezone.now(),
            }
            cache.set("operator-stats", operator_stats, 300)  # Cache for 5 minutes
        except Exception:
            operator_stats = {"total_operators": 0, "operators_with_vehicles": 0, "datetime": None}
    
    # Get last sync information
    last_sync = cache.get("last-sync", {})
    if not last_sync:
        try:
            from busstops.models import DataSource
            bustimes_source = DataSource.objects.filter(name="Bustimes API").first()
            if bustimes_source and bustimes_source.datetime:
                last_sync = {
                    "datetime": bustimes_source.datetime,
                    "source": "Bustimes API",
                }
            else:
                last_sync = {"datetime": None, "source": None}
            cache.set("last-sync", last_sync, 300)  # Cache for 5 minutes
        except Exception:
            last_sync = {"datetime": None, "source": None}
    
    stats = [
        {"label": "Middleware", "value": len(settings.MIDDLEWARE)},
        {"label": "Users", "value": User.objects.count()},
        {"label": "Trusted users", "value": User.objects.filter(trusted=True).count()},
        {"label": "Operators", "value": Operator.objects.count()},
        {"label": "Liveries", "value": Livery.objects.count()},
        {
            "label": "Pending edits",
            "value": VehicleRevision.objects.filter(pending=True).count(),
        },
        {
            "label": "Pending requests",
            "value": DataChangeLog.objects.filter(
                source__in=REQUEST_SOURCES,
                status=DataChangeLog.STATUS_PENDING,
            ).count(),
        },
        {
            "label": "Models",
            "value": sum(len(section["items"]) for section in model_sections),
        },
    ]

    featured = []
    for wanted in (
        "vehicles.livery",
        "vehicles.vehicle",
        "busstops.operator",
        "busstops.operatorgroup",
        "busstops.organisation",
        "accounts.user",
    ):
        for section in model_sections:
            match = next((item for item in section["items"] if item["label"] == wanted), None)
            if match:
                featured.append(match)
                break

    shortcuts = [
        {"label": "Requests", "url": reverse("requests_home")},
        {"label": "Pending edits", "url": "/vehicles/edits?status=pending"},
        {"label": "Fleet import", "url": "/fleet/import"},
        {"label": "Django admin", "url": reverse("admin:index")},
    ]

    return render(
        request,
        "dashboard_home.html",
        {
            "object": DashboardPage(),
            "breadcrumb": [DashboardPage()],
            "stats": stats,
            "featured_models": featured,
            "model_sections": model_sections,
            "shortcuts": shortcuts,
            "system_health": system_health,
            "import_status": import_status,
            "statistics": statistics,
            "service_stats": service_stats,
            "stop_stats": stop_stats,
            "operator_stats": operator_stats,
            "last_sync": last_sync,
        },
    )


@login_required
@transaction.atomic
def dashboard_add_model(request, app_label, model_name):
    require_dashboard_access(request)
    item = get_dashboard_model_item(request, app_label, model_name)
    model_admin = item["model_admin"]
    if not item["can_add"]:
        raise PermissionDenied

    form_class = model_admin.get_form(request, obj=None, change=False)
    saved_object = None

    if request.method == "POST":
        form = form_class(request.POST, request.FILES)
        if form.is_valid():
            saved_object = form.save(commit=False)
            model_admin.save_model(request, saved_object, form, change=False)
            model_admin.save_related(request, form, [], change=False)
            form = form_class()
    else:
        form = form_class()

    return render(
        request,
        "dashboard_add_model.html",
        {
            "object": DashboardPage(),
            "breadcrumb": [
                DashboardPage(),
                DashboardBreadcrumbItem(item["plural_title"], item["manage_url"] or item["add_url"]),
                DashboardBreadcrumbItem(
                    f"Add {item['title'].lower()}",
                    reverse(
                        "dashboard_add_model",
                        kwargs={
                            "app_label": item["app_label"],
                            "model_name": item["model_name"],
                        },
                    ),
                ),
            ],
            "dashboard_model": item,
            "form": form,
            "form_sections": get_dashboard_form_sections(model_admin, request, form),
            "saved_object": saved_object,
        },
    )


class LiveryDetailView(DetailView):
    model = Livery
    template_name = "livery_detail.html"

    def get_queryset(self):
        queryset = Livery.objects.annotate(vehicles_count=Count("vehicle"))
        if self.request.user.has_perm("vehicles.change_livery"):
            return queryset
        return queryset.filter(published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        object = self.object
        livery_vehicles = apply_vehicle_schema_compat(
            Vehicle.objects.select_related("vehicle_type", "operator").filter(
                livery=object,
                **current_fleet_filter(withdrawn=False, preserved=False),
            )
        )
        model_breakdown = (
            livery_vehicles.exclude(vehicle_type__isnull=True)
            .values("vehicle_type__name")
            .annotate(total=Count("id"))
            .order_by("-total", "vehicle_type__name")[:12]
        )
        context["breadcrumb"] = [self.object]
        context["preview_css"] = self.object.left_css or (
            self.object.colours and get_css(self.object.colours.split())
        )
        context["model_breakdown"] = model_breakdown
        context["example_vehicles"] = livery_vehicles.order_by(
            "fleet_number", "fleet_code", "reg", "code"
        )[:100]
        context["can_edit_livery"] = self.request.user.has_perm("vehicles.change_livery")
        if context["can_edit_livery"]:
            context["livery_form"] = kwargs.get("livery_form") or forms.LiveryInlineForm(
                instance=self.object
            )

        # Get previous operators from vehicle history events (repaint events)
        try:
            from vehicle_history.models import VehicleHistoryEvent, EventType
            previous_operators = []
            repaint_events = VehicleHistoryEvent.objects.filter(
                event_type=EventType.REPAINT,
                metadata__to_livery=object.id,
            ).select_related("vehicle__operator").order_by('-event_date', '-created_at')

            for event in repaint_events:
                vehicle = event.vehicle
                if vehicle.operator:
                    previous_operators.append({
                        'operator': vehicle.operator,
                        'joined_fleet': event.event_date.strftime('%m-%Y') if event.event_date else None,
                    })

            # Remove duplicates while preserving order
            seen = set()
            unique_operators = []
            for item in previous_operators:
                operator_id = item['operator'].id
                if operator_id not in seen:
                    seen.add(operator_id)
                    unique_operators.append(item)

            context['previous_operators'] = unique_operators
        except Exception:
            # If vehicle_history app is not available or has issues, skip
            context['previous_operators'] = []

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not request.user.has_perm("vehicles.change_livery"):
            raise PermissionDenied
        form = forms.LiveryInlineForm(request.POST, request.FILES, instance=self.object)
        if form.is_valid():
            form.save()
            return redirect(self.object.get_absolute_url())
        context = self.get_context_data(livery_form=form)
        return self.render_to_response(context)


@require_safe
def livery_list(request):
    liveries = (
        Livery.objects.filter(published=True)
        .annotate(vehicles_count=Count("vehicle"))
        .order_by("-vehicles_count", "name")
    )

    for livery in liveries:
        if not livery.left_css and livery.colours:
            livery.preview_css = get_css(livery.colours.split())
        else:
            livery.preview_css = livery.left_css

    return render(
        request,
        "livery_list.html",
        {
            "breadcrumb": [LiveriesPage()],
            "liveries": liveries,
        },
    )


revision_display_related_fields = (
    "from_type",
    "to_type",
    "from_operator",
    "to_operator",
    "from_livery",
    "to_livery",
    "from_garage",
    "to_garage",
)


@login_required
def edit_vehicle(request, **kwargs):
    check_user(request)

    edit_related = ["vehicle_type", "livery", "operator", "garage"]
    if "latest_journey_id" in _vehicle_db_columns():
        edit_related.append("latest_journey")
    vehicle = get_object_or_404(
        apply_vehicle_schema_compat(
            Vehicle.objects.select_related(*edit_related)
        ),
        **kwargs,
    )

    if not request.user.is_superuser and not vehicle.is_editable():
        # Allow trusted users to edit vehicles in historical fleets
        if not (request.user.trusted and vehicle.historical_fleet_id):
            raise PermissionDenied()

    form_data = ensure_vehicle_revision_rules(request, vehicle)
    if hasattr(form_data, "status_code"):
        return form_data

    user_can_edit_operator(request, vehicle.operator)

    context = {
        "previous": vehicle.get_previous(),
        "next": vehicle.get_next(),
    }

    revision = None

    try:
        context["vehicle_unique_id"] = vehicle.latest_journey_data["Extensions"][
            "VehicleJourney"
        ]["VehicleUniqueId"]
    except (KeyError, TypeError):
        pass

    # Check if advanced mode is requested via query parameter
    advanced_mode = "advanced" in request.GET

    form = forms.EditVehicleForm(
        form_data,
        vehicle=vehicle,
        user=request.user,
        sibling_vehicles=(context["previous"], context["next"]),
        advanced=advanced_mode,
    )

    context["livery"] = vehicle.livery

    if form_data:
        if form.has_changed() is False or form.changed_data == ["summary"]:
            form.add_error(None, "You haven't changed anything")

        if form.is_valid():
            data = {key: form.cleaned_data[key] for key in form.changed_data if key not in {"add_previous_operator", "add_previous_operator_joined_fleet"}}
            custom_column_updates = form.get_operator_vehicle_column_updates()
            if custom_column_updates:
                data["operator_vehicle_columns"] = custom_column_updates
            
            advanced_field_updates = form.get_advanced_field_updates()
            if advanced_field_updates:
                data["advanced"] = advanced_field_updates

            # Check for existing pending revisions before creating new one
            has_pending = False
            if "operator" in data:
                if VehicleRevision.objects.filter(vehicle=vehicle, to_operator=data["operator"], pending=True).exists():
                    form.add_error("operator", "There's already a pending edit for that")
                    has_pending = True
            if "operated_by" in data and not has_pending:
                if VehicleRevision.objects.filter(vehicle=vehicle, to_operated_by=data["operated_by"], pending=True).exists():
                    form.add_error("operated_by", "There's already a pending edit for that")
                    has_pending = True
            if "vehicle_type" in data and not has_pending:
                if VehicleRevision.objects.filter(vehicle=vehicle, to_type=data["vehicle_type"], pending=True).exists():
                    form.add_error("vehicle_type", "There's already a pending edit for that")
                    has_pending = True
            if "colours" in data and not has_pending:
                if VehicleRevision.objects.filter(vehicle=vehicle, to_livery=data["colours"], pending=True).exists():
                    form.add_error("colours", "There's already a pending edit for that")
                    has_pending = True
            if "garage" in data and not has_pending:
                if VehicleRevision.objects.filter(vehicle=vehicle, to_garage=data["garage"], pending=True).exists():
                    form.add_error("garage", "There's already a pending edit for that")
                    has_pending = True
            
            if has_pending:
                return render(request, f"vehicles/edit_vehicle.html", context)

            revision, features = get_revision(vehicle, data)

            revision.user = request.user
            revision.created_at = timezone.now()
            revision.pending = True
            try:
                with transaction.atomic():
                    revision.save()
                    VehicleRevisionFeature.objects.bulk_create(features)

                    if request.user.trusted:
                        apply_revision(revision, features)
                        revision.pending = False
                        revision.save(update_fields=["pending"])

                    context["revision"] = revision
                    form = None

            except IntegrityError as e:
                # This should rarely happen now due to pre-checks, but handle edge cases
                if "unique_pending_livery" in str(e):
                    form.add_error("colours", "There's already a pending edit for that")
                elif "unique_pending_type" in str(e):
                    form.add_error("vehicle_type", "There's already a pending edit for that")
                elif "unique_pending_operator" in str(e):
                    form.add_error("operator", "There's already a pending edit for that")
                elif "unique_pending_garage" in str(e):
                    form.add_error("garage", "There's already a pending edit for that")
                elif "unique_pending_operated_by" in str(e):
                    form.add_error("operated_by", "There's already a pending edit for that")
                elif (
                    "vehicle_operator_and_code" in str(e)
                    or "vehicle_operator_and_code_live" in str(e)
                ):
                    form.add_error("operator", f"{form.cleaned_data['operator']} already has a vehicle with the code {vehicle.code}")
                else:
                    raise

        if form:
            context["livery"] = form.cleaned_data.get("colours")

    if form:
        recent_edits_filter = Q(created_at__gte=Now() - datetime.timedelta(days=7))
        pending_edits = vehicle.vehiclerevision_set.filter(
            Q(pending=True) | recent_edits_filter
        )
        if not (request.user.trusted or request.user.is_superuser):
            pending_edits = vehicle.vehiclerevision_set.filter(
                Q(pending=True)
                | (recent_edits_filter & Q(disapproved=False))
                | (recent_edits_filter & Q(disapproved=True, user=request.user))
            )
        context["pending_edits"] = pending_edits.select_related(
            *revision_display_related_fields
        ).prefetch_related("vehiclerevisionfeature_set__feature")

    if vehicle.operator:
        context["breadcrumb"] = [vehicle.operator, Vehicles(vehicle=vehicle), vehicle]
    else:
        context["breadcrumb"] = [vehicle]

    # Get previous operators from vehicle history events
    try:
        from vehicle_history.models import VehicleHistoryEvent, EventType
        previous_operators = []
        transfer_events = VehicleHistoryEvent.objects.filter(
            vehicle=vehicle,
            event_type=EventType.TRANSFER,
        ).order_by('-event_date', '-created_at')

        for event in transfer_events:
            metadata = event.metadata or {}
            if 'from_operator' in metadata:
                try:
                    from busstops.models import Operator
                    operator = Operator.objects.get(id=metadata['from_operator'])
                    previous_operators.append({
                        'operator': operator,
                        'joined_fleet': event.event_date.strftime('%m-%Y') if event.event_date else None,
                    })
                except Operator.DoesNotExist:
                    pass

        context['previous_operators'] = previous_operators
    except Exception:
        # If vehicle_history app is not available or has issues, skip
        context['previous_operators'] = []

    response = render(
        request,
        "edit_vehicle.html",
        {
            **context,
            "form": form,
            "object": vehicle,
            "vehicle": vehicle,
        },
    )

    # for the ImgBB upload widget
    response["Cross-Origin-Opener-Policy"] = "unsafe-none"

    return response


@login_required
def vehicle_compare(request, **kwargs):
    if not request.user.trusted:
        raise PermissionDenied()

    edit_related = ["vehicle_type", "livery", "operator", "garage"]
    if "latest_journey_id" in _vehicle_db_columns():
        edit_related.append("latest_journey")
    vehicle = get_object_or_404(
        apply_vehicle_schema_compat(
            Vehicle.objects.select_related(*edit_related)
        ),
        **kwargs,
    )

    if not request.user.is_superuser and not vehicle.is_editable():
        # Allow trusted users to edit vehicles in historical fleets
        if not (request.user.trusted and vehicle.historical_fleet_id):
            raise PermissionDenied()

    # Fetch bustimes vehicle data by registration
    bustimes_vehicle = None
    if vehicle.reg:
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
            if data.get("results"):
                bustimes_vehicle = data["results"][0]
        except (requests.RequestException, ValueError, KeyError) as exc:
            logging.warning("Could not fetch Bustimes vehicle data: %s", exc)

    # Create form for local vehicle (editable)
    form = forms.EditVehicleForm(
        None,
        vehicle=vehicle,
        user=request.user,
        sibling_vehicles=(vehicle.get_previous(), vehicle.get_next()),
    )

    context = {
        "form": form,
        "object": vehicle,
        "vehicle": vehicle,
        "bustimes_vehicle": bustimes_vehicle,
        "breadcrumb": [vehicle.operator, Vehicles(vehicle=vehicle), vehicle] if vehicle.operator else [vehicle],
    }

    return render(request, "vehicle_compare.html", context)


@login_required
def requests_home(request):
    visible_logs = limit_request_logs_visibility(
        get_request_logs_queryset().order_by("-created_at"), request
    )
    recent_requests = sorted(
        (wrap_request_log(log) for log in visible_logs[:50]),
        key=lambda entry: entry.created_at,
        reverse=True,
    )
    return render(
        request,
        "requests.html",
        {
            "entries": recent_requests,
            "breadcrumb": [RequestsPage()],
        },
    )


@login_required
def report_bug(request):
    if request.method == "POST":
        category = request.POST.get("category")
        severity = request.POST.get("severity")
        summary = request.POST.get("summary")

        if not all([category, severity, summary]):
            return render(
                request,
                "requests.html",
                {
                    "error": "All fields are required",
                    "entries": [],
                    "breadcrumb": [RequestsPage()],
                },
            )

        try:
            webhook_url = os.environ.get("BUG_DISCORD_ENDPOINT")
            if webhook_url:
                severity_num = int(severity)
                emoji_map = {
                    1: "🟢",
                    2: "🟢",
                    3: "🟡",
                    4: "🟡",
                    5: "🟠",
                    6: "🟠",
                    7: "🔴",
                    8: "🔴",
                    9: "🔴",
                    10: "🚨",
                }
                emoji = emoji_map.get(severity_num, "⚪")

                embed = {
                    "title": f"{emoji} Bug Report - {category.upper()}",
                    "description": summary,
                    "fields": [
                        {"name": "Category", "value": category, "inline": True},
                        {"name": "Severity", "value": f"{severity_num}/10", "inline": True},
                        {"name": "Reported by", "value": str(request.user), "inline": True},
                    ],
                    "color": severity_num * 100000 if severity_num <= 5 else 16711680,
                }

                response = requests.post(
                    webhook_url,
                    json={"embeds": [embed]},
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            return render(
                request,
                "requests.html",
                {
                    "success": "Bug report submitted successfully",
                    "entries": [],
                    "breadcrumb": [RequestsPage()],
                },
            )
        except Exception as e:
            return render(
                request,
                "requests.html",
                {
                    "error": f"Failed to submit bug report: {str(e)}",
                    "entries": [],
                    "breadcrumb": [RequestsPage()],
                },
            )

    return redirect("requests_home")





@login_required
def generic_request_page(request):
    form = forms.GenericRequestForm(request.POST or None)
    request_log = None

    if request.method == "POST" and form.is_valid():
        try:
            webhook_url = os.environ.get("REQUEST_DISCORD_ENDPOINT")
            if webhook_url:
                category = form.cleaned_data["category"]
                title = form.cleaned_data["title"]
                description = form.cleaned_data["description"]
                priority = form.cleaned_data["priority"]
                
                emoji_map = {
                    "low": "🟢",
                    "medium": "🟡",
                    "high": "🟠",
                    "urgent": "🔴",
                }
                emoji = emoji_map.get(priority, "⚪")

                embed = {
                    "title": f"{emoji} {category.upper()} Request",
                    "description": description,
                    "fields": [
                        {"name": "Title", "value": title, "inline": True},
                        {"name": "Category", "value": category, "inline": True},
                        {"name": "Priority", "value": priority.capitalize(), "inline": True},
                        {"name": "Reported by", "value": str(request.user), "inline": True},
                    ],
                    "color": 16711680 if priority == "urgent" else (11750886 if priority == "high" else (16776960 if priority == "medium" else 5068894)),
                }

                response = requests.post(
                    webhook_url,
                    json={"embeds": [embed]},
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()

            return render(
                request,
                "request_form.html",
                {
                    "form": None,
                    "request_log": {"success": True},
                    "request_title": "Generic Request",
                    "submit_label": "Submit Request",
                    "breadcrumb": [RequestsPage()],
                },
            )
        except Exception as e:
            return render(
                request,
                "request_form.html",
                {
                    "form": form,
                    "error": f"Failed to submit request: {str(e)}",
                    "request_title": "Generic Request",
                    "submit_label": "Submit Request",
                    "breadcrumb": [RequestsPage()],
                },
            )

    return render(
        request,
        "request_form.html",
        {
            "form": form,
            "request_log": request_log,
            "request_title": "Generic Request",
            "submit_label": "Submit Request",
            "breadcrumb": [RequestsPage()],
        },
    )


@login_required
def request_new_vehicle(request, slug=None):
    check_user(request)

    operator = None
    if slug:
        operator = get_object_or_404(
            Operator.objects.select_related("group", "region"), slug=slug
        )
        user_can_edit_operator(request, operator)

    form_data = ensure_vehicle_revision_rules(request, operator or RequestsPage())
    if hasattr(form_data, "status_code"):
        return form_data

    form = forms.NewVehicleRequestForm(form_data, operator=operator)
    request_log = None

    if form_data and form.is_valid():
        cleaned_data = form.cleaned_data
        operator = form.get_operator()
        user_can_edit_operator(request, operator)
        code = cleaned_data["code"]
        request_key = f"create:{operator.pk}:{code.upper()}"

        # Check if a vehicle with this code already exists in the database
        if Vehicle.objects.filter(operator=operator, code__iexact=code).exists():
            existing_vehicle = Vehicle.objects.get(operator=operator, code__iexact=code)
            form.add_error(
                "code",
                f"A vehicle with code '{code}' already exists for this operator. "
                f"See: {existing_vehicle.get_absolute_url()}"
            )
        
        # Check if a vehicle with this registration already exists in the database
        reg = cleaned_data.get("reg")
        if reg:
            # RegField already normalizes the registration (uppercase, removes spaces)
            if Vehicle.objects.filter(reg__iexact=reg).exists():
                existing_vehicle = Vehicle.objects.filter(reg__iexact=reg).first()
                form.add_error(
                    "reg",
                    f"A vehicle with registration '{reg}' already exists. "
                    f"See: {existing_vehicle.get_absolute_url()}"
                )
        
        if not form.errors and DataChangeLog.objects.filter(
            target_model="vehicles.vehicle",
            target_pk=request_key,
            operation="create",
            status=DataChangeLog.STATUS_PENDING,
        ).exists():
            form.add_error("code", "There is already a pending request for that code.")
        else:
            fields = {"code": code, "operator": operator.pk}
            changes = {
                "code": {"from": "", "to": code},
                "operator": {"from": "", "to": str(operator)},
            }

            if cleaned_data["spare_ticket_machine"]:
                cleaned_data["notes"] = "Spare ticket machine"

            fleet_code = cleaned_data["fleet_number"].strip()
            if fleet_code:
                fields["fleet_code"] = fleet_code
                changes["fleet number"] = {"from": "", "to": fleet_code}
                if fleet_code.isdigit():
                    fields["fleet_number"] = int(fleet_code)

            field_map = {
                "reg": "reg",
                "vehicle_type": "vehicle_type",
                "branding": "branding",
                "rear_advert": "rear_advert",
                "name": "name",
                "previous_reg": "prev_registration",
                "notes": "notes",
                "withdrawn": "withdrawn",
                "preserved": "preserved",
                "fleet_support_vehicle": "fleet_support_vehicle",
                "vor": "vor",
                "awaiting_delivery": "awaiting_delivery",
                "trainer_vehicle": "trainer_vehicle",
                "demonstrator": "demonstrator",
            }

            for form_field, model_field in field_map.items():
                value = cleaned_data.get(form_field)
                if value in ("", None, False):
                    continue
                if hasattr(value, "pk"):
                    fields[model_field] = value.pk
                    changes[form_field.replace("_", " ")] = {"from": "", "to": str(value)}
                else:
                    fields[model_field] = value
                    display_value = "Yes" if value is True else value
                    changes[form_field.replace("_", " ")] = {
                        "from": "",
                        "to": display_value,
                    }

            if cleaned_data.get("colours"):
                livery = cleaned_data["colours"]
                fields["livery"] = livery.pk
                changes["livery"] = {"from": "", "to": str(livery)}
            elif cleaned_data.get("other_colour"):
                fields["colours"] = cleaned_data["other_colour"]
                changes["colours"] = {"from": "", "to": cleaned_data["other_colour"]}

            all_features = list(cleaned_data["features"]) + list(
                cleaned_data["accessibility_features"]
            )
            feature_ids = [feature.pk for feature in all_features]
            if feature_ids:
                changes["features"] = {
                    "from": "",
                    "to": ", ".join(str(feature) for feature in all_features),
                }

            custom_column_updates = {
                key: value
                for key, value in form.get_operator_vehicle_column_updates().items()
                if value
            }
            if custom_column_updates:
                fields["data"] = custom_column_updates
                labels_by_slug = {
                    column.slug: column.name for column in form.operator_vehicle_columns
                }
                for key, value in custom_column_updates.items():
                    changes[labels_by_slug.get(key, key)] = {"from": "", "to": value}

            request_log = create_request_log(
                source="vehicle_request",
                target_model="vehicles.vehicle",
                target_pk=request_key,
                target_repr=f"{operator} {code}",
                fields=fields,
                changes=changes,
                summary=cleaned_data.get("summary", ""),
                user=request.user,
                many_to_many={"features": feature_ids},
            )
            form = None

    return render(
        request,
        "new_vehicle_request.html",
        {
            "form": form,
            "object": operator,
            "operator": operator,
            "request_log": request_log,
            "breadcrumb": (
                [operator, Vehicles(operator=operator)]
                if operator
                else [RequestsPage()]
            ),
        },
    )


@login_required
def request_new_service(request):
    check_user(request)

    form_data = ensure_vehicle_revision_rules(request, RequestsPage())
    if hasattr(form_data, "status_code"):
        return form_data

    form = forms.NewServiceRequestForm(form_data)
    request_log = None

    if form_data and form.is_valid():
        operator = form.cleaned_data["operator"]
        user_can_edit_operator(request, operator)

        line_name = form.cleaned_data["line_name"].strip()
        service_code = form.cleaned_data["service_code"].strip()
        request_key = f"create:service:{operator.pk}:{(service_code or line_name).upper()}"

        if DataChangeLog.objects.filter(
            source="service_request",
            target_model="busstops.service",
            target_pk=request_key,
            status=DataChangeLog.STATUS_PENDING,
        ).exists():
            form.add_error("line_name", "There is already a pending request for that service.")
        else:
            title = f"{operator} {line_name}"
            fields = {
                "line_name": line_name,
                "description": form.cleaned_data["description"].strip(),
                "service_code": service_code,
            }
            changes = {
                "line name": {"from": "", "to": line_name},
                "operator": {"from": "", "to": str(operator)},
            }
            if fields["description"]:
                changes["description"] = {"from": "", "to": fields["description"]}
            if service_code:
                changes["service code"] = {"from": "", "to": service_code}

            request_log = create_request_log(
                source="service_request",
                target_model="busstops.service",
                target_pk=request_key,
                target_repr=title,
                fields=fields,
                changes=changes,
                summary=form.cleaned_data["summary"],
                user=request.user,
                many_to_many={"operator": [operator.pk]},
            )
            form = None

    return render(
        request,
        "request_form.html",
        {
            "form": form,
            "request_log": request_log,
            "request_title": "Request a service",
            "submit_label": "Request service",
            "breadcrumb": [RequestsPage()],
        },
    )


@login_required
def request_new_operator(request):
    check_user(request)

    form_data = ensure_vehicle_revision_rules(request, RequestsPage())
    if hasattr(form_data, "status_code"):
        return form_data

    form = forms.NewOperatorRequestForm(form_data)
    request_log = None

    if form_data and form.is_valid():
        noc = form.cleaned_data["noc"]
        name = form.cleaned_data["name"].strip()
        request_key = f"create:operator:{noc}"

        if DataChangeLog.objects.filter(
            source="operator_request",
            target_model="busstops.operator",
            target_pk=request_key,
            status=DataChangeLog.STATUS_PENDING,
        ).exists():
            form.add_error("noc", "There is already a pending request for that operator.")
        elif Operator.objects.filter(name__iexact=name).exists():
            form.add_error("name", "An operator with that name already exists.")
        else:
            fields = {
                "noc": noc,
                "name": name,
            }
            changes = {
                "operator code": {"from": "", "to": noc},
                "name": {"from": "", "to": name},
            }
            
            # Add optional fields if provided
            if form.cleaned_data.get("logo"):
                fields["logo"] = form.cleaned_data["logo"]
                changes["logo"] = {"from": "", "to": form.cleaned_data["logo"]}
            if form.cleaned_data.get("vehicle_mode"):
                fields["vehicle_mode"] = form.cleaned_data["vehicle_mode"]
                changes["vehicle mode"] = {"from": "", "to": form.cleaned_data["vehicle_mode"]}
            if form.cleaned_data.get("group"):
                fields["group"] = str(form.cleaned_data["group"])
                changes["group"] = {"from": "", "to": str(form.cleaned_data["group"])}
            if form.cleaned_data.get("region"):
                fields["region"] = str(form.cleaned_data["region"])
                changes["region"] = {"from": "", "to": str(form.cleaned_data["region"])}
            
            request_log = create_request_log(
                source="operator_request",
                target_model="busstops.operator",
                target_pk=request_key,
                target_repr=f"{noc} {name}",
                fields=fields,
                changes=changes,
                summary=form.cleaned_data["summary"],
                user=request.user,
            )
            form = None

    return render(
        request,
        "request_form.html",
        {
            "form": form,
            "request_log": request_log,
            "request_title": "Request an operator",
            "submit_label": "Request operator",
            "breadcrumb": [RequestsPage()],
        },
    )


@login_required
def request_new_vehicle_model(request):
    check_user(request)

    form_data = ensure_vehicle_revision_rules(request, RequestsPage())
    if hasattr(form_data, "status_code"):
        return form_data

    form = forms.NewVehicleModelRequestForm(form_data)
    request_log = None

    if form_data and form.is_valid():
        name = form.cleaned_data["name"].strip()
        manufacturer = form.cleaned_data["manufacturer"]
        request_key = f"create:vehicle-type:{name.upper()}"

        if DataChangeLog.objects.filter(
            source="vehicle_type_request",
            target_model="vehicles.vehicletype",
            target_pk=request_key,
            status=DataChangeLog.STATUS_PENDING,
        ).exists():
            form.add_error("name", "There is already a pending request for that vehicle model.")
        elif VehicleType.objects.filter(name__iexact=name).exists():
            form.add_error("name", "That vehicle model already exists.")
        else:
            changes = {"name": {"from": "", "to": name}}
            fields = {"name": name}
            if manufacturer:
                fields["manufacturer"] = manufacturer.pk
                changes["manufacturer"] = {"from": "", "to": str(manufacturer)}

            request_log = create_request_log(
                source="vehicle_type_request",
                target_model="vehicles.vehicletype",
                target_pk=request_key,
                target_repr=name,
                fields=fields,
                changes=changes,
                summary=form.cleaned_data["summary"],
                user=request.user,
            )
            form = None

    return render(
        request,
        "request_form.html",
        {
            "form": form,
            "request_log": request_log,
            "request_title": "Request a vehicle model",
            "submit_label": "Request vehicle model",
            "breadcrumb": [RequestsPage()],
        },
    )




@require_POST
@login_required
@transaction.atomic
def request_log_action(request, log_id, action):
    log = get_object_or_404(
        get_request_logs_queryset().select_for_update(of=["self"]),
        id=log_id,
    )

    requester_id = (log.payload or {}).get("requested_by_id")
    reason = unquote(request.headers.get("HX-Prompt", ""))

    if action == "reject" and requester_id == request.user.id and not can_apply_request_log(request.user, log):
        from busstops.data_changes import reject_pending_change

        log = reject_pending_change(
            log, user=request.user, reason=reason or "Cancelled by requester."
        )
    else:
        if action == "apply":
            if not can_apply_request_log(request.user, log):
                raise PermissionDenied
        elif action == "reject":
            if not (can_apply_request_log(request.user, log) or can_cancel_request_log(request.user, log)):
                raise PermissionDenied
        else:
            raise PermissionDenied
        if action == "apply":
            from busstops.data_changes import apply_pending_change

            log = apply_pending_change(log, user=request.user)
        else:
            from busstops.data_changes import reject_pending_change

            log = reject_pending_change(log, user=request.user, reason=reason or "Declined")

    return render(
        request,
        "request_log.html",
        {"request_entry": wrap_request_log_for_user(log, request.user).object, "user": request.user},
    )


@require_POST
@login_required
@transaction.atomic
def vehicle_revision_action(request, revision_id, action):
    revision = get_object_or_404(
        apply_vehicle_schema_compat(
            VehicleRevision.objects.select_related(
                *revision_display_related_fields, "vehicle"
            ),
            prefix="vehicle__",
        )
        .filter(Q(pending=True) | Q(approved_by=request.user))
        .select_for_update(of=["self"]),
        id=revision_id,
    )

    if action == "disapprove" and request.user.id == revision.user_id:
        revision.delete()  # cancel one's own edit
        return HttpResponse("")
    else:
        # Allow superusers to approve their own requests
        if request.user.id == revision.user_id and not request.user.is_superuser:
            raise PermissionDenied("You cannot approve your own request.")
        assert request.user.trusted or request.user.is_superuser

    revision.disapproved_reason = unquote(request.headers.get("HX-Prompt", ""))
    revision.approved_by = request.user
    revision.approved_at = Now()

    if action == "apply":
        apply_revision(revision)
        revision.pending = False
        revision.disapproved = False
    elif action == "disapprove":
        revision.pending = False
        revision.disapproved = True

    revision.save()

    return render(request, "vehicle_revision.html", {"revision": revision})


@require_safe
def vehicle_edits(request):
    revisions = (
        apply_vehicle_schema_compat(
            VehicleRevision.objects.select_related(
                *revision_display_related_fields, "user", "vehicle"
            ),
            prefix="vehicle__",
        )
        .prefetch_related("vehiclerevisionfeature_set__feature")
        .order_by("-id")
    )

    default_status = (
        "pending"
        if request.user.is_authenticated
        and (request.user.trusted or request.user.is_superuser)
        else "approved"
    )
    vehicle = None
    f = filters.VehicleRevisionFilter(
        request.GET or {"status": default_status, "show": "all"}, queryset=revisions
    )
    if request.user.is_anonymous or not (
        request.user.trusted
        or request.user.is_superuser
        or request.GET.get("user") == str(request.user.id)
    ):
        f.filters["status"].field.choices = [("approved", "approved")]
        f.form.fields["status"].choices = [("approved", "approved")]

    if f.is_valid():
        vehicle_id = f.form.cleaned_data.get("vehicle")
        if vehicle_id:
            vehicle = (
                Vehicle.objects.select_related("operator").filter(pk=vehicle_id).first()
            )
        request_logs = filter_request_logs(get_request_logs_queryset(), f.form, request)
        show = f.form.cleaned_data.get("show") or "all"
        entries = []
        if show != "requests" and not show.endswith("_request"):
            entries = [wrap_vehicle_revision(revision) for revision in f.qs]
        entries += [wrap_request_log_for_user(log, request.user) for log in request_logs]
        entries.sort(key=lambda entry: entry.created_at, reverse=True)

        paginator = Paginator(entries, 25)
        page = paginator.get_page(request.GET.get("page"))
    else:
        page = None

    return render(
        request,
        "vehicle_edits.html",
        {
            "filter": f,
            "entries": page,
            "reset_query": f"status={default_status}&show=all",
            "vehicle": vehicle,
        },
    )


class VehicleJourneyDetailView(DetailView):
    model = VehicleJourney


@require_safe
def journey_json(request, pk, vehicle_id=None, service_id=None):
    journey = get_object_or_404(
        VehicleJourney.objects.select_related("trip", "vehicle"), pk=pk
    )

    data = {
        "vehicle_id": journey.vehicle_id,
        "service_id": journey.service_id,
        "trip_id": journey.trip_id,
        "datetime": timezone.localtime(journey.datetime),
        "route_name": journey.route_name,
        "code": journey.code,
        "destination": journey.destination,
        "direction": journey.direction,
        "current": journey.vehicle and journey.id == journey.vehicle.latest_journey_id,
    }

    if redis_client:
        locations = redis_client and redis_client.lrange(journey.get_redis_key(), 0, -1)
    else:
        locations = None

    if locations:
        locations = [
            VehicleLocation.decode_appendage(location) for location in locations
        ]
        locations.sort(key=lambda location: location["datetime"])

        data["locations"] = []

        stationary = False
        previous = None
        previous_coords = None
        for location in locations:
            coords = location["coordinates"]

            if previous_coords:
                dx = coords[0] - previous_coords[0]
                dy = coords[1] - previous_coords[1]
                if dx * dx + dy * dy < 2.5e-7:  # 0.0005 degrees squared
                    stationary = True
                elif stationary:
                    # mark end of stationary period
                    data["locations"].append(previous)
                    stationary = False

            if not stationary:
                data["locations"].append(location)

                previous_coords = coords

            previous = location

        if stationary:  # add last location
            data["locations"].append(location)

        del locations

    # if not trip - calculate using time and first location?
    # if not trip:
    #     Trip

    if journey.trip:
        data["stops"] = []
        # previous_latlong = None

        trips = journey.trip.get_trips()
        if trips == [journey.trip]:
            stoptimes = trips[0].stoptime_set.select_related("stop__locality")
        else:
            stoptimes = (
                StopTime.objects.filter(trip__in=trips)
                .order_by("trip__start", "id")
                .select_related("stop__locality")
            )
            stoptimes = contiguous_stoptimes_only(stoptimes, journey.trip.id)

        for stoptime in stoptimes:
            stop = stoptime.stop
            # if stop := stoptime.stop:
            #     if stop.latlong:
            #         if previous_latlong:
            #             heading = calculate_bearing(previous_latlong, stop.latlong)
            #         else:
            #             heading = None
            #         previous_latlong = stop.latlong
            data["stops"].append(
                {
                    "id": stoptime.id,
                    "atco_code": stoptime.stop_id,
                    "name": (
                        stop.get_name_for_timetable() if stop else stoptime.stop_code
                    ),
                    "aimed_arrival_time": stoptime.arrival_time(),
                    "aimed_departure_time": stoptime.departure_time(),
                    "minor": stoptime.is_minor(),
                    "heading": stop and stop.get_heading(),
                    "coordinates": stop and stop.latlong and stop.latlong.coords,
                }
            )
    elif journey.service_id:
        stop_usages = StopUsage.objects.filter(
            service_id=journey.service_id
        ).select_related("stop__locality")
        data["stops"] = [
            {
                "id": su.id,
                "atco_code": su.stop_id,
                "name": su.stop.get_name_for_timetable(),
                "heading": su.stop.get_heading(),
                "coordinates": su.stop.latlong and su.stop.latlong.coords,
                "minor": not su.timing_point,
                "inbound": su.inbound,
                "line_name": su.line_name.upper(),
            }
            for i, su in enumerate(stop_usages)
        ]
        del stop_usages

    if data.get("stops") and data.get("locations"):
        # filter by line name
        if "line_name" in data["stops"][0]:
            line_name = journey.route_name.upper()
            if any(stop["line_name"] == line_name for stop in data["stops"]):
                data["stops"] = [
                    stop for stop in data["stops"] if stop["line_name"] == line_name
                ]

        # only stops with coordinates
        stops = [stop for stop in data["stops"] if stop["coordinates"]]

        if stops:
            stop_coords = [stop["coordinates"][::-1] for stop in stops]
            vehicle_coords = [
                location["coordinates"][::-1] for location in data["locations"]
            ]
            # pre-build stop headings array for azimuth filtering; NaN = unknown
            stop_headings = np.array(
                [s["heading"] if s["heading"] is not None else np.nan for s in stops],
                dtype=float,
            )
            try:
                haversine_vector_results = haversine_vector(
                    stop_coords,
                    vehicle_coords,
                    Unit.METERS,
                    comb=True,
                )
            except ValueError as e:
                logging.exception(e)
            else:
                for distances, location in zip(
                    haversine_vector_results, data["locations"]
                ):
                    vehicle_heading = location.get("direction")
                    if vehicle_heading is not None:
                        # mask stops whose heading differs by ≥ 90° from vehicle
                        # heading_diff in [0, 180]; NaN headings are always kept
                        heading_diff = np.abs(
                            ((stop_headings - vehicle_heading) + 180) % 360 - 180
                        )
                        aligned = np.isnan(heading_diff) | (heading_diff < 90)
                        if aligned.any():
                            idx = int(np.argmin(np.where(aligned, distances, np.inf)))
                        else:
                            idx = int(np.argmin(distances))
                    else:
                        idx = int(np.argmin(distances))

                    if distances[idx] < 100:
                        stops[idx]["actual_departure_time"] = location["datetime"]

            # work out which direction we're going in
            inbound = datetime.timedelta()
            outbound = datetime.timedelta()
            previous = None

            for stop in stops:
                if "inbound" in stop and "actual_departure_time" in stop:
                    if previous and previous["inbound"] == stop["inbound"]:
                        difference = (
                            stop["actual_departure_time"]
                            - previous["actual_departure_time"]
                        )
                        if stop["inbound"]:
                            inbound += difference
                        else:
                            outbound += difference

                    previous = stop

            # whichever sum-of-differences is bigger is the direction of travel
            if inbound > outbound:
                data["stops"] = [stop for stop in data["stops"] if stop["inbound"]]
            elif inbound < outbound:
                data["stops"] = [stop for stop in data["stops"] if not stop["inbound"]]

    next_previous_filter = {"date": journey.date}
    if service_id:
        next_previous_filter["service_id"] = service_id
        data["vehicle"] = str(journey.vehicle)
    else:
        next_previous_filter["vehicle_id"] = journey.vehicle_id

    try:
        next_journey = journey.get_next_by_datetime(**next_previous_filter)
    except VehicleJourney.DoesNotExist:
        pass
    else:
        data["next"] = {
            "id": next_journey.id,
            "datetime": timezone.localtime(next_journey.datetime),
        }

    try:
        previous_journey = journey.get_previous_by_datetime(**next_previous_filter)
    except VehicleJourney.DoesNotExist:
        pass
    else:
        data["previous"] = {
            "id": previous_journey.id,
            "datetime": timezone.localtime(previous_journey.datetime),
        }

    return JsonResponse(data)


@require_safe
def latest_journey_debug(request, **kwargs):
    vehicle = get_object_or_404(Vehicle, **kwargs, latest_journey_data__isnull=False)

    # redact possible personal information
    try:
        del vehicle.latest_journey_data["Extensions"]["VehicleJourney"]["DriverRef"]
    except (KeyError, TypeError):
        pass

    return JsonResponse(vehicle.latest_journey_data, safe=False)


def debug(request):
    form = forms.DebuggerForm(request.POST or None)
    result = None
    if form.is_valid():
        data = form.cleaned_data["data"]
        try:
            item = json.loads(data)
        except ValueError as e:
            form.add_error("data", e)
        else:
            result = {
                "message": "Legacy live import debugging is disabled. Live vehicles are read from Bustimes JSON.",
                "data": item,
            }

    return render(request, "vehicles/debug.html", {"form": form, "result": result})


@csrf_exempt
def siri_post(request, uuid):
    subscription = get_object_or_404(SiriSubscription, uuid=uuid)
    last_post_key = subscription.get_status_key().replace("_status", "_last_post")

    if request.method == "GET":
        last_post = cache.get(last_post_key)
        return HttpResponse(
            last_post["body"], content_type=last_post["headers"]["content-type"]
        )

    body = request.body.decode()
    data = xmltodict.parse(body, force_list=["VehicleActivity"])

    handle_siri_post(uuid, data)

    cache.set(last_post_key, {"headers": request.headers, "body": body}, None)

    return HttpResponse(
        xmltodict.unparse(
            {
                "Siri": {
                    "@xmlns": "http://www.siri.org.uk/siri",
                    "@version": "2.0",
                    "@xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                    "@xsi:schemaLocation": "http://www.siri.org.uk/siri http://www.siri.org.uk/schema/2.0/xsd/siri.xsd",
                    "DataReceivedAcknowledgement": {
                        "ResponseTimestamp": timezone.now().isoformat(),
                        "ConsumerRef": subscription.requestor_ref,
                        "Status": True,
                    },
                }
            }
        ),
        content_type="application/xml",
    )


@csrf_exempt
@require_POST
def overland(request, uuid):
    subscription = get_object_or_404(SiriSubscription, uuid=uuid)

    data = json.loads(request.body)

    for item in data["locations"][-1:]:
        when = item["properties"]["timestamp"]
        device_id = item["properties"]["device_id"]
        operator, vehicle, line_name, journey_ref = device_id.split(":")
        lon, lat = item["geometry"]["coordinates"]
        activity = {
            "RecordedAtTime": when,
            "MonitoredVehicleJourney": {
                "OperatorRef": operator,
                "VehicleRef": vehicle,
                "PublishedLineName": line_name,
                "VehicleJourneyRef": journey_ref,
                "VehicleLocation": {
                    "Longitude": lon,
                    "Latitude": lat,
                },
            },
        }

        handle_siri_post(
            uuid,
            {
                "Siri": {
                    "ServiceDelivery": {
                        "ResponseTimestamp": when,
                        "VehicleMonitoringDelivery": {
                            "VehicleActivity": [activity],
                        },
                    }
                }
            },
        )

    cache.set(
        subscription.get_status_key().replace("_status", "_last_post"),
        {"headers": request.headers, "body": request.body.decode()},
        None,
    )

    # https://github.com/aaronpk/Overland-iOS#api
    return JsonResponse({"result": "ok"})


@require_POST
def clear_operator_logs(request, slug):
    """
    Clear all fleet logs (ride and driving) for a specific operator.
    Only accessible to superusers.
    """
    if not request.user.is_superuser:
        raise PermissionDenied

    operator = get_object_or_404(Operator, slug=slug)

    # Get all vehicles for this operator
    vehicles = Vehicle.objects.filter(operator=operator)

    # Clear all ride logs for these vehicles
    ride_logs_deleted = FleetRideLog.objects.filter(vehicle__in=vehicles).delete()[0]

    # Clear all driving logs for these vehicles
    driving_logs_deleted = FleetDrivingLog.objects.filter(vehicle__in=vehicles).delete()[0]

    messages.success(
        request,
        f"Cleared {ride_logs_deleted} ride logs and {driving_logs_deleted} driving logs for {operator.name}."
    )

    return redirect(operator.get_vehicles_url())
