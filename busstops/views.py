"""View definitions."""

import csv
import datetime
import json
import os
import logging
import re
from functools import lru_cache
from http import HTTPStatus
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.utils import ProgrammingError
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.decorators import login_required
from django.contrib.gis.db.models import Extent
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import LineString, Point
from django.contrib.postgres.aggregates import ArrayAgg, BoolOr
from itertools import groupby, pairwise
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.contrib.sitemaps import Sitemap
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import (
    Count,
    Exists,
    F,
    Max,
    Min,
    OuterRef,
    Prefetch,
    Q,
    When,
    Case,
    Value,
    prefetch_related_objects,
)
from django.db.models.functions import Coalesce, Now
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import get_template
from django.urls import URLPattern, URLResolver, get_resolver, resolve, reverse
from django.utils import timezone
from django.utils.cache import patch_response_headers
from django.utils.functional import SimpleLazyObject
from django.utils.html import escape
from django.views.csrf import csrf_failure as django_csrf_failure
from django.views.decorators.cache import cache_control
from django.views.decorators.http import last_modified, require_http_methods
from django.views.generic.detail import DetailView
from redis.exceptions import ConnectionError
from sql_util.utils import Exists, SubqueryCount, SubqueryMax, SubqueryMin
from ukpostcodeutils import validation

from buses.utils import cdn_cache_control
from accounts.models import User
from bustimes.models import Garage, Route, RouteLink, RouteWaypoint, StopTime, Trip
from bustimes.utils import get_calendars, get_other_trips_in_block
from departures import live
from vehicles.models import Livery, Vehicle, VehicleJourney, VehicleType, get_css
from vehicles.utils import redis_client

# Import fares models defensively
try:
    from fares.models import FareTable, Tariff, Ticket
    FARES_AVAILABLE = True
except (ImportError, ProgrammingError):
    FARES_AVAILABLE = False

# Import disruptions models defensively
try:
    from disruptions.models import Consequence, Situation
    DISRUPTIONS_AVAILABLE = True
except (ImportError, ProgrammingError):
    DISRUPTIONS_AVAILABLE = False

# Import vosa models defensively
try:
    from vosa.models import Registration
except (ImportError, ProgrammingError):
    Registration = None
from vehicles.views import (
    check_user,
    ensure_vehicle_revision_rules,
    operator_vehicles as reference_operator_vehicles,
    wrap_request_log_for_user,
)

from . import forms
from .fleet_imports import (
    build_livery_mapping_rows,
    collect_livery_mappings,
    commit_mass_rows,
    parse_mass_rows,
    rows_text_from_upload,
)
from .middleware import get_site_usage_entries
from .models import (
    AdminArea,
    BlogPost,
    BlogTag,
    DataChangeLog,
    DataSource,
    District,
    GovernmentAuthority,
    Locality,
    Manufacturer,
    HomepageNotice,
    Organisation,
    Operator,
    OperatorGroup,
    PaymentMethod,
    PreservationGroup,
    Region,
    RouteNotice,
    Service,
    ServiceCode,
    ServiceColour,
    StopArea,
    StopGroup,
    StopPoint,
)
from .recently_viewed import get_recently_viewed, record_recently_viewed
from .utils import (
    build_depot_map_html,
    get_bounding_box,
    get_manufacturer_sites,
    get_operator_depots,
    get_operator_social_links,
    get_organisation_depots,
    get_theme_source,
    serialize_depot_map_points,
)

BUSTIMES_SLUG_SCHEME = "bustimes-slug"
BUSTIMES_SCHEME = "bustimes"
SITE_ROOT_URL = "https://eeveeit.uk"
SITEMAP_URLS = (
    f"{SITE_ROOT_URL}/",
    f"{SITE_ROOT_URL}/fleet/",
    f"{SITE_ROOT_URL}/register/",
    f"{SITE_ROOT_URL}/accounts/discord-link/",
    f"{SITE_ROOT_URL}/accounts/request-driver-status/",
    f"{SITE_ROOT_URL}/contact/",
    f"{SITE_ROOT_URL}/data-sources/",
)

operator_has_current_services = Exists("service", filter=Q(service__current=True))


def get_service_situations(service, operators):
    """Currently-published situations affecting a service (or its operators)."""
    consequences = Consequence.objects.filter(
        Q(services=service) | (Q(operators__in=operators, services=None))
    )
    return (
        Situation.objects.filter(
            Exists(consequences.filter(situation=OuterRef("id"))),
            publication_window__contains=Now(),
            current=True,
        )
        .order_by("publication_window")
        .prefetch_related(
            Prefetch(
                "consequence_set",
                queryset=consequences.prefetch_related("stops"),
                to_attr="consequences",
            ),
            "validityperiod_set",
        )
    )


def build_stop_situations(situations, when=None):
    """Map atco_code → Situation for stops affected (on the given date)."""
    stop_situations = {}
    for situation in situations:
        if when and not situation.applies_on(when):
            continue
        for consequence in situation.consequences:
            for stop in consequence.stops.all():
                stop_situations[stop.atco_code] = situation
    return stop_situations


def apply_stop_situations(timetable, stop_situations):
    """Mark disrupted stops in a timetable (applied lazily when rendered)."""
    if timetable and stop_situations:
        timetable.stop_situations = stop_situations
        # situations affect the rendered (and cached) timetable html
        timetable.cache_key += ":" + ":".join(
            sorted(str(s.id) for s in set(stop_situations.values()))
        )


def get_blog_posts_queryset():
    return BlogPost.objects.filter(published=True).prefetch_related("tags")


def user_can_manage_blog(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            user.is_superuser
            or user.has_perm("busstops.add_blogpost")
            or user.has_perm("busstops.change_blogpost")
        )
    )


def user_can_create_blog_post(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (user.is_superuser or user.has_perm("busstops.add_blogpost"))
    )


def user_can_edit_blog_post(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (user.is_superuser or user.has_perm("busstops.change_blogpost"))
    )


def get_blog_manager_queryset(user):
    if not user_can_manage_blog(user):
        raise PermissionDenied
    return BlogPost.objects.prefetch_related("tags")


@require_http_methods(["GET"])
def blog_index(request):
    paginator = Paginator(get_blog_posts_queryset(), 12)
    posts = paginator.get_page(request.GET.get("page"))
    tags = BlogTag.objects.filter(posts__published=True).distinct().order_by("name")
    return render(
        request,
        "blog_index.html",
        {
            "posts": posts,
            "page_obj": posts,
            "tag": None,
            "tags": tags,
            "can_manage_blog": user_can_manage_blog(request.user),
        },
    )


@require_http_methods(["GET"])
def blog_tag_detail(request, slug):
    tag = get_object_or_404(BlogTag, slug=slug)
    paginator = Paginator(get_blog_posts_queryset().filter(tags=tag), 12)
    posts = paginator.get_page(request.GET.get("page"))
    tags = BlogTag.objects.filter(posts__published=True).distinct().order_by("name")
    return render(
        request,
        "blog_index.html",
        {
            "posts": posts,
            "page_obj": posts,
            "tag": tag,
            "object": tag,
            "tags": tags,
            "can_manage_blog": user_can_manage_blog(request.user),
        },
    )


class BlogPostDetailView(DetailView):
    model = BlogPost
    template_name = "blog_post_detail.html"

    def get_queryset(self):
        if user_can_manage_blog(self.request.user):
            return BlogPost.objects.prefetch_related("tags")
        return get_blog_posts_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_manage_blog"] = user_can_manage_blog(self.request.user)
        context["can_edit_blog_post"] = user_can_edit_blog_post(self.request.user)
        return context


@require_http_methods(["GET"])
def blog_manage(request):
    posts = get_blog_manager_queryset(request.user).order_by(
        "-published",
        "-published_at",
        "-updated_at",
    )
    return render(
        request,
        "blog_manage.html",
        {
            "posts": posts,
            "draft_count": posts.filter(published=False).count(),
            "published_count": posts.filter(published=True).count(),
            "can_create_blog_post": user_can_create_blog_post(request.user),
        },
    )


@require_http_methods(["GET", "POST"])
def blog_post_create(request):
    if not user_can_create_blog_post(request.user):
        raise PermissionDenied

    form = forms.BlogPostEditorForm(request.POST or None)
    saved_object = None
    if request.method == "POST" and form.is_valid():
        publish = "publish" in request.POST
        saved_object = form.save(publish=publish)
        if publish:
            return redirect(saved_object.get_absolute_url())
        return redirect("blog_manage")

    return render(
        request,
        "blog_post_form.html",
        {
            "form": form,
            "object": saved_object,
            "is_create": True,
        },
    )


@require_http_methods(["GET", "POST"])
def blog_post_edit(request, slug):
    if not user_can_edit_blog_post(request.user):
        raise PermissionDenied

    post = get_object_or_404(BlogPost.objects.prefetch_related("tags"), slug=slug)
    form = forms.BlogPostEditorForm(request.POST or None, instance=post)
    if request.method == "POST" and form.is_valid():
        publish = post.published
        if "publish" in request.POST:
            publish = True
        elif "save_draft" in request.POST:
            publish = False
        post = form.save(publish=publish)
        if publish:
            return redirect(post.get_absolute_url())
        return redirect("blog_manage")

    return render(
        request,
        "blog_post_form.html",
        {
            "form": form,
            "object": post,
            "is_create": False,
        },
    )


@lru_cache(maxsize=1)
def vehicle_db_columns():
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


def current_vehicle_filters(**filters):
    columns = vehicle_db_columns()
    unsupported = {
        "withdrawn": "withdrawn",
        "preserved": "preserved",
        "operator": "operator_id",
        "operator_id__in": "operator_id",
        "operator_id": "operator_id",
        "latest_journey__isnull": "latest_journey_id",
    }
    for key, column in unsupported.items():
        if key in filters and column not in columns:
            filters.pop(key)
    if "historical_fleet_id" in columns:
        filters["historical_fleet__isnull"] = True
    return filters


@lru_cache(maxsize=1)
def missing_vehicle_field_names():
    columns = vehicle_db_columns()
    missing = []
    for field in Vehicle._meta.concrete_fields:
        column = getattr(field, "column", None)
        if column and column not in columns:
            missing.append(field.name)
    return tuple(missing)


def apply_vehicle_schema_compat(queryset):
    missing = missing_vehicle_field_names()
    if missing:
        queryset = queryset.defer(*missing)
    return queryset


operator_has_current_services_or_vehicles = operator_has_current_services | Exists(
    "vehicle",
    filter=Q(
        **current_vehicle_filters(
            withdrawn=False,
            preserved=False,
            latest_journey__isnull=False,
        )
    ),
)


def get_colours(services):
    colours = set(service.colour_id for service in services if service.colour_id)
    if colours:
        return ServiceColour.objects.filter(id__in=colours)


def compact_text(value):
    return str(value or "").strip()


def has_route_geometry(data):
    geometry = (data or {}).get("geometry")
    if not geometry:
        return False

    coordinates = geometry.get("coordinates")
    if not coordinates:
        return False

    return bool(coordinates)


def get_geometry_extent(geometry):
    coordinates = (geometry or {}).get("coordinates") or []
    if not coordinates:
        return

    if geometry.get("type") == "LineString":
        points = coordinates
    else:
        points = [point for line in coordinates for point in line]

    if not points:
        return

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def get_bustimes_base_url():
    return getattr(settings, "BUSTIMES_API_BASE_URL", "https://bustimes.org").rstrip("/")


@login_required
def fleet_import(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    preview_rows = []
    livery_mapping_rows = []
    created = 0
    updated = 0
    errors = 0

    if request.method == "POST":
        form = forms.FleetImportForm(request.POST, request.FILES)
        if form.is_valid():
            default_operator = form.cleaned_data["operator"]
            historical_fleet = form.cleaned_data["historical_fleet"]
            historical_year = form.cleaned_data["historical_year"]
            manual_livery_selection = form.cleaned_data["manual_livery_selection"]
            rows_text = form.cleaned_data.get("rows_text") or ""
            upload = form.cleaned_data.get("upload")
            try:
                if upload:
                    rows_text = rows_text_from_upload(default_operator, upload)
            except ValueError as exc:
                form.add_error("upload", str(exc))

            if not form.errors and not rows_text.strip():
                form.add_error(None, "Paste rows or upload a completed file.")

            if not form.errors:
                preview_rows = parse_mass_rows(
                    default_operator,
                    rows_text,
                    default_historical_fleet=historical_fleet,
                    default_historical_year=historical_year,
                )
                livery_mapping_rows = build_livery_mapping_rows(
                    preview_rows,
                    manual_livery_selection=manual_livery_selection,
                )
                livery_mappings = collect_livery_mappings(request.POST, livery_mapping_rows)
                for item in livery_mapping_rows:
                    item["selected_livery_id"] = livery_mappings.get(item["raw_name"], item["selected_livery_id"])

                form = forms.FleetImportForm(
                    initial={
                        "operator": default_operator.pk if default_operator else "",
                        "historical_fleet": historical_fleet.pk if historical_fleet else "",
                        "historical_year": historical_year or "",
                        "manual_livery_selection": manual_livery_selection,
                        "rows_text": rows_text,
                    }
                )

                if request.POST.get("action") == "commit":
                    created, updated, errors = commit_mass_rows(
                        default_operator,
                        preview_rows,
                        livery_mappings=livery_mappings,
                        default_historical_fleet=historical_fleet,
                        default_historical_year=historical_year,
                    )
    else:
        form = forms.FleetImportForm()

    liveries = Livery.objects.order_by("name")
    context = {
        "form": form,
        "rows": preview_rows,
        "livery_mapping_rows": livery_mapping_rows,
        "liveries": liveries,
        "can_commit": any(not row["errors"] for row in preview_rows),
        "created": created,
        "updated": updated,
        "errors": errors,
        "title": "Fleet import",
    }
    return render(request, "fleet_import.html", context)


def link_bustimes_service(service, item):
    if not service.pk:
        return

    for scheme, code in (
        (BUSTIMES_SCHEME, compact_text(item.get("id"))),
        (BUSTIMES_SLUG_SCHEME, compact_text(item.get("slug"))),
    ):
        if code and not service.servicecode_set.filter(scheme=scheme, code=code).exists():
            ServiceCode.objects.create(service=service, scheme=scheme, code=code)


def resolve_bustimes_service_identifier(service):
    bustimes_slug = (
        service.servicecode_set.filter(scheme=BUSTIMES_SLUG_SCHEME)
        .values_list("code", flat=True)
        .first()
    )
    if bustimes_slug:
        return bustimes_slug

    bustimes_id = (
        service.servicecode_set.filter(scheme=BUSTIMES_SCHEME)
        .values_list("code", flat=True)
        .first()
    )
    if bustimes_id:
        return bustimes_id

    candidate_codes = [compact_text(service.service_code)]
    candidate_codes.extend(
        service.servicecode_set.filter(scheme="ServiceCode").values_list("code", flat=True)
    )
    candidate_codes = [code for code in dict.fromkeys(candidate_codes) if code]

    if not candidate_codes:
        return

    search_url = f"{get_bustimes_base_url()}/api/services/"
    line_name = compact_text(service.line_name).casefold()

    for code in candidate_codes:
        try:
            response = requests.get(
                search_url,
                params={"search": code, "limit": 25},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        for item in payload.get("results", []):
            item_service_code = compact_text(item.get("service_code"))
            if item_service_code.casefold() != code.casefold():
                continue

            item_line_name = compact_text(item.get("line_name")).casefold()
            if line_name and item_line_name and item_line_name != line_name:
                continue

            link_bustimes_service(service, item)
            return compact_text(item.get("slug") or item.get("id"))


def get_bustimes_service_map_data(service):
    cache_key = f"service-map-bustimes:{service.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None

    identifier = resolve_bustimes_service_identifier(service)
    if not identifier:
        cache.set(cache_key, False, 300)
        return

    try:
        response = requests.get(
            f"{get_bustimes_base_url()}/services/{identifier}.json",
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        cache.set(cache_key, False, 300)
        return

    if has_route_geometry(payload):
        cache.set(cache_key, payload, 900)
        return payload

    cache.set(cache_key, False, 300)


def version(request):
    if commit_hash := os.environ.get("COMMIT_HASH"):
        return HttpResponse(
            f"""<a href="https://github.com/jclgoodwin/bustimes.org/commit/{commit_hash}">{commit_hash}</a>""",
        )
    return HttpResponse(
        os.environ.get("KAMAL_CONTAINER_NAME"), content_type="text/plain"
    )


def flixbus_affiliate_link(**kwargs) -> str:
    query = {"awinmid": 110896, "awinaffid": 242611, **kwargs}
    return f"https://www.awin1.com/cread.php?{urlencode(query)}"


def flibco_affiliate_link(
    ued="https://www.flibco.com/en/shuttle/bus-coach-london-stansted-airport", **kwargs
):
    return flixbus_affiliate_link(awinmid=53945, ued=ued, **kwargs)


def get_operator_tickets_link(operator, operator_codes=None):
    if operator_codes is None:
        operator_codes = operator.operatorcode_set.annotate(source_name=F("source__name"))

    if any(code.source_name == "MyTrip" for code in operator_codes):
        return reverse("operator_tickets", kwargs={"slug": operator.slug})
    if operator.name == "FlixBus":
        return flixbus_affiliate_link(
            clickref="ot",
            ued="https://www.flixbus.co.uk/bus-routes/london-london-stansted-airport",
        )
    if operator.name == "Flibco":
        return flibco_affiliate_link(clickref="ot")
    if operator.name == "National Express":
        return "https://nationalexpress.prf.hn/click/camref:1011ljPYw"
    return ""


def format_price(amount):
    text = f"{amount:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    elif text.endswith("0"):
        text = text[:-1]
    return f"£{text}"


def clean_tariff_name(name):
    return (
        (name or "")
        .removeprefix("Tariff for ")
        .removesuffix(" fares")
        .replace(" Conc ", " Concession ")
        .replace(" YP ", " Young Person ")
        .replace(" Ch ", " Child ")
        .replace("_", " ")
        .replace(" AD ", " Adult ")
    )


TICKET_FAMILY_PATTERN = re.compile(
    r"^(?P<family>.+?)(?:\s+(?:\d+\s+Day|\d+\s+Week|Annual|Summer|Group|Flexi|"
    r"DayRider|MegaRider|StudentRider|WeekRider|NightRider|Xtra)\b)",
    re.IGNORECASE,
)


def get_ticket_family_name(name):
    cleaned_name = clean_tariff_name(name).strip()
    match = TICKET_FAMILY_PATTERN.match(cleaned_name)
    if match:
        family = match.group("family").strip(" -")
        if family:
            return family
    return cleaned_name


def get_ticket_variant_name(name, family):
    cleaned_name = clean_tariff_name(name).strip()
    if cleaned_name.lower().startswith(family.lower()):
        variant = cleaned_name[len(family) :].strip(" -")
        if variant:
            return variant
    return cleaned_name


def get_ticket_title(tariff):
    if not FARES_AVAILABLE:
        return ""
    for table in tariff.faretable_set.all():
        product = table.preassigned_fare_product
        if product and product.name:
            return product.name
    return clean_tariff_name(tariff.name)


def get_ticket_description(tariff):
    if not FARES_AVAILABLE:
        return ""
    for table in tariff.faretable_set.all():
        product = table.preassigned_fare_product
        product_description = getattr(product, "description", "")
        if product_description:
            return product_description
        if table.description:
            return table.description
        user_profile = table.user_profile
        if user_profile and user_profile.description:
            return user_profile.description
    return ""


def serialize_tariff_ticket(tariff):
    if not FARES_AVAILABLE:
        return None
    ticket_name = get_ticket_title(tariff)
    family_name = get_ticket_family_name(ticket_name)
    channel_names = []
    for table in tariff.faretable_set.all():
        if table.sales_offer_package and table.sales_offer_package.name:
            if table.sales_offer_package.name not in channel_names:
                channel_names.append(table.sales_offer_package.name)

    price_summaries = []
    for price in tariff.price_set.all():
        label_parts = []
        if price.sales_offer_package and price.sales_offer_package.name:
            label_parts.append(price.sales_offer_package.name)
            if price.sales_offer_package.name not in channel_names:
                channel_names.append(price.sales_offer_package.name)
        if price.time_interval and price.time_interval.name:
            label_parts.append(price.time_interval.name)
        label = " - ".join(label_parts)
        summary = format_price(price.amount)
        if label:
            summary = f"{label}: {summary}"
        if summary not in price_summaries:
            price_summaries.append(summary)

    if not price_summaries and tariff.distancematrixelement_set.exists():
        price_summaries.append("Zone-to-zone fares available")
    if not price_summaries and tariff.faretable_set.exists():
        price_summaries.append("Fare table available")

    return {
        "id": tariff.id,
        "name": ticket_name,
        "family": family_name,
        "variant_name": get_ticket_variant_name(ticket_name, family_name),
        "description": get_ticket_description(tariff),
        "url": tariff.get_absolute_url(),
        "prices": price_summaries,
        "channels": channel_names,
        "valid_between": tariff.valid_between,
        "service_ids": sorted(service.id for service in tariff.services.all()),
    }


def serialize_manual_ticket(ticket):
    price_parts = []
    if ticket.adult_price is not None:
        price_parts.append(f"A: {format_price(ticket.adult_price)}")
    if ticket.child_price is not None:
        price_parts.append(f"C: {format_price(ticket.child_price)}")

    detail_parts = []
    if ticket.zone:
        detail_parts.append(f"zone {ticket.zone}")
    if ticket.days_valid_for is not None:
        day_label = "day" if ticket.days_valid_for == 1 else "days"
        detail_parts.append(f"{ticket.days_valid_for} {day_label}")

    description_parts = []
    if ticket.description:
        description_parts.append(ticket.description)
    if detail_parts:
        description_parts.append(" ".join(detail_parts))

    return {
        "id": f"manual-{ticket.id}",
        "name": ticket.name,
        "family": ticket.ticket_type or ticket.name,
        "variant_name": ticket.name,
        "description": ". ".join(description_parts),
        "url": ticket.get_absolute_url(),
        "prices": [" ".join(price_parts)] if price_parts else [],
        "channels": [],
        "valid_between": None,
        "service_ids": sorted(service.id for service in ticket.get_accepted_services()),
    }


def get_published_tariffs():
    if not FARES_AVAILABLE:
        return []
    try:
        return Tariff.objects.filter(source__published=True).prefetch_related(
            "services",
            "distancematrixelement_set",
            "faretable_set__preassigned_fare_product",
            "faretable_set__sales_offer_package",
            "price_set__sales_offer_package",
            "price_set__time_interval",
        )
    except Exception:
        return []


def get_manual_tickets():
    if not FARES_AVAILABLE:
        return []
    try:
        return Ticket.objects.select_related("operator").prefetch_related(
            "ticketacceptance_set__service"
        )
    except Exception:
        return []


def get_operator_ticket_count(operator):
    if not FARES_AVAILABLE:
        return 0
    try:
        return (
            get_published_tariffs().filter(operators=operator).distinct().count()
            + get_manual_tickets().filter(operator=operator).count()
        )
    except Exception:
        return 0


def group_serialized_tickets(tickets, by_service_signature=False):
    grouped = {}

    for ticket in tickets:
        service_signature = (
            tuple(ticket["service_ids"]) if by_service_signature else tuple()
        )
        group_key = (ticket["family"], service_signature)
        group = grouped.setdefault(
            group_key,
            {
                "id": ticket["id"],
                "name": ticket["family"],
                "url": ticket["url"],
                "service_ids": ticket["service_ids"],
                "channels": [],
                "variants": {},
            },
        )

        for channel in ticket["channels"]:
            if channel not in group["channels"]:
                group["channels"].append(channel)

        variant_key = ticket["variant_name"]
        variant = group["variants"].setdefault(
            variant_key,
            {
                "id": ticket["id"],
                "name": ticket["variant_name"],
                "full_name": ticket["name"],
                "description": ticket["description"],
                "url": ticket["url"],
                "prices": [],
                "channels": [],
            },
        )

        if not variant["description"] and ticket["description"]:
            variant["description"] = ticket["description"]

        for price in ticket["prices"]:
            if price not in variant["prices"]:
                variant["prices"].append(price)

        for channel in ticket["channels"]:
            if channel not in variant["channels"]:
                variant["channels"].append(channel)

    results = []
    for group in grouped.values():
        variants = sorted(
            group["variants"].values(),
            key=lambda variant: (variant["name"] != variant["full_name"], variant["name"]),
        )
        results.append(
            {
                "id": group["id"],
                "name": group["name"],
                "url": group["url"],
                "channels": group["channels"],
                "variant_count": len(variants),
                "route_count": len(group["service_ids"]),
                "variants": variants,
            }
        )

    return sorted(results, key=lambda ticket: (ticket["name"], ticket["variant_count"]))


def index(request):
    """
    Homepage view displaying site statistics, organisations, manufacturers,
    preservation groups, government authorities, and user-specific content.
    
    For authenticated users, includes pinned operators and favourites.
    """
    today = timezone.localdate()
    notices = HomepageNotice.objects.filter(is_active=True).filter(
        Q(from_date__isnull=True) | Q(from_date__lte=today),
        Q(to_date__isnull=True) | Q(to_date__gte=today),
    )
    context = {
        "stats": {
            "vehicles": Vehicle.objects.filter(
                **current_vehicle_filters(
                    withdrawn=False,
                    preserved=False,
                )
            ).count(),
            "operators": Operator.objects.filter(
                ceased_operations_on__isnull=True
            ).filter(
                Exists(
                    Vehicle.objects.filter(
                        operator=OuterRef('pk'),
                        **current_vehicle_filters(
                            withdrawn=False,
                            preserved=False,
                        )
                    )
                )
            ).count(),
            "vehicle_types": VehicleType.objects.count(),
            "liveries": Livery.objects.count(),
            "users": User.objects.count(),
        },
        "recently_viewed": get_recently_viewed(request),
        "homepage_notices": notices,
        "organisations": Organisation.objects.order_by("name"),
        "manufacturers": Manufacturer.objects.order_by("name"),
        "preservation_groups": PreservationGroup.objects.annotate(
            vehicle_count=Count("preserved_vehicles")
        ).order_by("name"),
        "government_authorities": GovernmentAuthority.objects.order_by("name"),
    }

    if request.user.is_authenticated:
        from fleet.models import PinnedOperator
        try:
            context["pinned_operators"] = (
                PinnedOperator.objects.filter(user=request.user)
                .select_related("operator")
                .order_by("created_at")
            )
        except Exception:
            context["pinned_operators"] = []
        
        # Add user favourites
        from favourites.models import Favourite, FavouriteType
        try:
            favourites = Favourite.objects.filter(user=request.user).select_related(
                "operator", "vehicle", "service"
            )
            context["favourite_operators"] = favourites.filter(
                favourite_type=FavouriteType.OPERATOR
            )
            context["favourite_vehicles"] = favourites.filter(
                favourite_type=FavouriteType.VEHICLE
            )
            context["favourite_services"] = favourites.filter(
                favourite_type=FavouriteType.SERVICE
            )
        except Exception:
            context["favourite_operators"] = []
            context["favourite_vehicles"] = []
            context["favourite_services"] = []

    return render(request, "index.html", context)


def not_found(request, exception):
    """Custom 404 handler view"""

    context = {}

    if request.resolver_match:
        if request.resolver_match.url_name == "service_detail" and exception.args:
            code = request.resolver_match.kwargs["slug"]
            service_code_parts = code.split("-")

            if len(service_code_parts) >= 4:
                suggestion = None
                services = Service.objects.filter(current=True).only("slug")

                # e.g. from '17-N4-_-y08-1' to '17-N4-_-y08':
                suggestion = services.filter(
                    service_code__icontains="_" + "-".join(service_code_parts[:4]),
                ).first()

                # e.g. from '46-holt-circular-1' to '46-holt-circular-2':
                if not suggestion and code.lower():
                    if service_code_parts[-1].isdigit():
                        slug = "-".join(service_code_parts[:-1])
                    else:
                        slug = "-".join(service_code_parts)
                    suggestion = services.filter(slug__startswith=slug).first()

                if suggestion:
                    return redirect(suggestion)

        elif request.resolver_match.url_name == "stoppoint_detail":
            try:
                return redirect(
                    StopPoint.objects.get(
                        naptan_code__iexact=request.resolver_match.kwargs["pk"]
                    )
                )
            except StopPoint.DoesNotExist:
                pass

        context["exception"] = exception
    elif request.path[:6] == "/STOP/":
        return redirect(f"/stops/{request.path[6:]}")
    elif len(request.path) > 1 and request.path.endswith("/"):
        try:
            resolver_match = resolve(request.path[:-1])
            return resolver_match.func(request, **resolver_match.kwargs)
        except Http404:
            pass

    # anonymise request (cos response may be cached)
    request.user = AnonymousUser

    context["ad"] = False
    response = render(request, "404.html", context)
    response.status_code = HTTPStatus.NOT_FOUND

    if not request.resolver_match:
        # no matching url pattern, cache for an hour
        patch_response_headers(response, cache_timeout=3600)

    return response


def csrf_failure(request, reason=""):
    logging.warning("CSRF failure: %s", reason)
    if (
        request.resolver_match
        and request.resolver_match.url_name == "login"
        and request.user.is_authenticated
    ):
        return HttpResponseRedirect(
            request.POST.get("next") or settings.LOGIN_REDIRECT_URL
        )
    return django_csrf_failure(request, reason)


@cdn_cache_control(max_age=300)
def operator_fleet_redirect(request, slug):
    operators = Operator.objects.only("slug")

    operator = operators.filter(slug=slug.lower()).first()
    if not operator:
        operator = operators.filter(noc__iexact=slug).first()
    if not operator:
        operator = get_object_or_404(
            operators,
            operatorcode__code=slug,
            operatorcode__source__name="slug",
        )

    return redirect("operator_vehicles", slug=operator.slug, permanent=True)


def get_operator_breadcrumb(operator):
    breadcrumb = []
    organisation = operator.organisation
    if not organisation and operator.group_id:
        organisation = operator.group.organisation
    if organisation:
        breadcrumb.append(organisation)
    if operator.group_id:
        breadcrumb.append(operator.group)
    if not breadcrumb and operator.region_id:
        breadcrumb.append(operator.region)
    breadcrumb.append(operator)
    return breadcrumb


def _add_blocks_tab_to_operator_fleet(response, slug):
    content_type = response.get("Content-Type", "")
    if response.status_code != HTTPStatus.OK or "text/html" not in content_type:
        return response

    charset = getattr(response, "charset", None) or "utf-8"
    html = response.content.decode(charset)
    routes_tab = f'<li><a href="/operators/{slug}/routes">Routes</a></li>'
    blocks_tab = f'<li><a href="/operators/{slug}/vehicles/blocks">Blocks</a></li>'
    html = html.replace(
        f'<li><a href="/operators/{slug}/vehicles">Routes</a></li>',
        routes_tab,
    )
    html = html.replace(
        f'href="/operators/{slug}/vehicles/map"',
        f'href="/operators/{slug}/map"',
    )

    if blocks_tab not in html:
        historical_tab_end = (
            f'<a href="/operators/{slug}/vehicles/historical">Historical fleets</a></li>'
        )
        if historical_tab_end in html:
            html = html.replace(
                historical_tab_end,
                f"{historical_tab_end}\n        {blocks_tab}",
                1,
            )
        elif '<ul class="tabs">' in html:
            tabs_start = html.find('<ul class="tabs">')
            tabs_end = html.find("</ul>", tabs_start)
            if tabs_end != -1:
                html = f"{html[:tabs_end]}        {blocks_tab}\n    {html[tabs_end:]}"

    try:
        operator = Operator.objects.get(slug=slug.lower())
    except Operator.DoesNotExist:
        operator = None
    if operator:
        services_count = operator.service_set.filter(current=True).count()
        if services_count and "Routes (" not in html:
            html = html.replace(
                f'<a href="/operators/{slug}/routes">Routes</a>',
                f'<a href="/operators/{slug}/routes">Routes ({services_count})</a>',
                1,
            )

        depots_count = len(get_operator_depots(operator))
        depots_tab = (
            f'<li><a href="/operators/{slug}/vehicles?tab=depots">'
            f"Garage map ({depots_count})</a></li>"
            if depots_count
            else ""
        )
        if depots_tab and "Garage map" not in html and '<ul class="tabs">' in html:
            routes_tab_end = "</li>"
            routes_index = html.find(f'href="/operators/{slug}/routes"')
            if routes_index != -1:
                routes_end = html.find(routes_tab_end, routes_index)
                if routes_end != -1:
                    html = (
                        f"{html[:routes_end + len(routes_tab_end)]}\n        "
                        f"{depots_tab}{html[routes_end + len(routes_tab_end):]}"
                    )

        tickets_count = get_operator_ticket_count(operator)
        if tickets_count:
            tickets_tab = (
                f'<li><a href="/operators/{slug}?tab=tickets">Tickets ({tickets_count})</a></li>'
            )
        else:
            tickets_link = get_operator_tickets_link(operator)
            tickets_tab = (
                f'<li><a href="{tickets_link}">Tickets</a></li>'
                if tickets_link
                else ""
            )
        if tickets_tab and tickets_tab not in html and '<ul class="tabs">' in html:
            tabs_start = html.find('<ul class="tabs">')
            tabs_end = html.find("</ul>", tabs_start)
            if tabs_end != -1:
                html = f"{html[:tabs_end]}        {tickets_tab}\n    {html[tabs_end:]}"

    response.content = html.encode(charset)
    response.headers["Content-Length"] = str(len(response.content))
    return response


def operator_vehicles(request, slug):
    response = reference_operator_vehicles(request, slug=slug)
    return _add_blocks_tab_to_operator_fleet(response, slug)


def operator_historical_vehicles(request, slug):
    response = reference_operator_vehicles(request, slug=slug, historical=True)
    return _add_blocks_tab_to_operator_fleet(response, slug)


def operator_blocks(request, slug):
    operators = Operator.objects.select_related("organisation", "group__organisation", "region")
    try:
        operator = operators.get(slug=slug.lower())
    except Operator.DoesNotExist:
        operator = get_object_or_404(
            operators,
            operatorcode__code=slug,
            operatorcode__source__name="slug",
        )
    
    # Get date from query parameter or use today
    try:
        blocks_date = datetime.date.fromisoformat(request.GET.get("date", ""))
    except (TypeError, ValueError):
        blocks_date = timezone.localdate()
    
    vehicles_count = Vehicle.objects.filter(
        **current_vehicle_filters(
            operator=operator,
            withdrawn=False,
            preserved=False,
        )
    ).count()
    depots_count = len(get_operator_depots(operator))
    services = operator.service_set.filter(current=True)
    services_count = services.count()
    tickets_count = get_operator_ticket_count(operator)
    map_exists = False
    if redis_client and (vehicles_count or services.filter(tracking=True).exists()):
        try:
            map_exists = redis_client.exists(f"operator{operator.noc}vehicles")
        except ConnectionError:
            pass

    return render(
        request,
        "operator_blocks.html",
        {
            "object": operator,
            "blocks_date": blocks_date,
            "today": timezone.localdate(),
            "breadcrumb": get_operator_breadcrumb(operator),
            "depots_count": depots_count,
            "map": map_exists,
            "services_count": services_count,
            "social_links": get_operator_social_links(operator),
            "tickets_link": get_operator_tickets_link(operator),
            "tickets_count": tickets_count,
            "vehicles_count": vehicles_count,
        },
    )


@cache_control(max_age=3600)
def robots_txt(request):
    "robots.txt"

    content = """User-agent: *
Allow: /

Sitemap: https://eeveeit.uk/sitemap.xml
"""

    return HttpResponse(content, content_type="text/plain")


@cache_control(max_age=3600)
def sitemap_xml(request):
    urls = "\n".join(f"  <url><loc>{escape(url)}</loc></url>" for url in SITEMAP_URLS)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
    return HttpResponse(content, content_type="application/xml")


def contact(request):
    """Contact page with form"""
    submitted = False
    if request.method == "POST":
        form = forms.ContactForm(request.POST, request=request)
        if form.is_valid():
            subject = form.cleaned_data["message"][:50].splitlines()[0]

            body = [
                form.cleaned_data["message"],
                form.cleaned_data["referrer"],
                request.headers.get("user-agent", ""),
            ]
            if request.user.is_authenticated:
                body.append(f"https://bustimes.org{request.user.get_absolute_url()}")
            body = "\n\n".join(body)

            message = EmailMessage(
                subject,
                body,
                '"{}" <contactform@bustimes.org>'.format(form.cleaned_data["name"]),
                ["contact@bustimes.org"],
                reply_to=[form.cleaned_data["email"]],
            )
            message.send()
            submitted = True
    else:
        referrer = request.headers.get("referer")
        initial = {
            "referrer": referrer,
            "message": request.GET.get("message"),
        }
        if request.user.is_authenticated:
            initial["email"] = request.user.email
        form = forms.ContactForm(initial=initial)
    return render(request, "contact.html", {"form": form, "submitted": submitted})


def status(request):
    context = {
        "sources": DataSource.objects.filter(
            name__in=["National Operator Codes", "NPTG", "NaPTAN", "Irish NaPTAN"]
        ),
        "bod_avl_status": {},
    }

    for key in ("bod_avl", "Transport_for_Wales", "Bus_Open_Data", "Todd's_Travel"):
        key = f"{key}_status"
        if status := cache.get(key):
            context["bod_avl_status"][key] = status

    context["statuses"] = cache.get_many(
        [
            "Realtime_Transport_Operators_status",
            "Irish_Citylink_status",
            "Translink_status",
            "Stagecoach_status",
            "Ember_status",
            "TfE_status",
            "jersey_status",
        ]
    ).items()

    return render(
        request,
        "status.html",
        context,
    )


@cache_control(max_age=3600)
def stops_mvt(request, z, x, y):
    """Mapbox Vector Tile endpoint for bus stops, replacing stops_json eventually."""
    if z < 10:
        return HttpResponse(b"", content_type="application/x-protobuf")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ST_AsMVT(tile, 'stops', 4096, 'geom')
            FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(sp.latlong, 3857),
                        ST_TileEnvelope(%s, %s, %s),
                        4096, 64, true
                    ) AS geom,
                    '/stops/' || sp.atco_code AS url,
                    sp.indicator,
                    sp.common_name,
                    COALESCE(l.name, '') AS locality_name,
                    COALESCE(
                        sp.heading,
                        CASE sp.bearing
                            WHEN 'N'  THEN 0
                            WHEN 'NE' THEN 45
                            WHEN 'E'  THEN 90
                            WHEN 'SE' THEN 135
                            WHEN 'S'  THEN 180
                            WHEN 'SW' THEN 225
                            WHEN 'W'  THEN 270
                            WHEN 'NW' THEN 315
                        END
                    ) AS bearing,
                    CASE
                        WHEN sp.indicator != '' AND LENGTH(sp.indicator) < 3
                             AND sp.indicator != LOWER(sp.indicator)
                            THEN sp.indicator
                        WHEN sp.indicator != ''
                             AND array_length(regexp_split_to_array(sp.indicator, '\\s+'), 1) = 2
                             AND LENGTH((regexp_split_to_array(sp.indicator, '\\s+'))[2]) < 3
                             AND LOWER((regexp_split_to_array(sp.indicator, '\\s+'))[1])
                                 IN ('stop','bay','stand','stance','gate','platform')
                            THEN (regexp_split_to_array(sp.indicator, '\\s+'))[2]
                        WHEN POSITION(' ' IN sp.common_name) > 0
                             AND LENGTH(regexp_replace(sp.common_name, '^.* ', '')) < 3
                             AND (   regexp_replace(sp.common_name, '^.* ', '') ~ '^[0-9]+$'
                                  OR regexp_replace(sp.common_name, '^.* ', '') ~ '^[A-Z]+$')
                            THEN regexp_replace(sp.common_name, '^.* ', '')
                        ELSE NULL
                    END AS icon,
                    (
                        SELECT STRING_AGG(DISTINCT su.line_name, ',' ORDER BY su.line_name)
                        FROM busstops_stopusage su
                        JOIN busstops_service svc ON su.service_id = svc.id
                        WHERE su.stop_id = sp.atco_code AND svc.current = true
                    ) AS line_names,
                    false AS stop_group
                FROM busstops_stoppoint sp
                LEFT JOIN busstops_locality l ON sp.locality_id = l.id
                WHERE
                    sp.latlong && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
                    AND EXISTS (
                        SELECT 1
                        FROM busstops_stopusage su
                        JOIN busstops_service svc ON su.service_id = svc.id
                        WHERE su.stop_id = sp.atco_code AND svc.current = true
                    )
                UNION ALL
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(sg.location, 3857),
                        ST_TileEnvelope(%s, %s, %s),
                        4096, 64, true
                    ) AS geom,
                    '/stop-groups/' || sg.slug AS url,
                    '' AS indicator,
                    sg.name AS common_name,
                    '' AS locality_name,
                    NULL AS bearing,
                    'G' AS icon,
                    (
                        SELECT STRING_AGG(DISTINCT su.line_name, ',' ORDER BY su.line_name)
                        FROM busstops_stopgroupstop sgs
                        JOIN busstops_stopusage su ON su.stop_id = sgs.stop_id
                        JOIN busstops_service svc ON su.service_id = svc.id
                        WHERE sgs.group_id = sg.id AND svc.current = true
                    ) AS line_names,
                    true AS stop_group
                FROM busstops_stopgroup sg
                WHERE
                    sg.active = true
                    AND sg.location IS NOT NULL
                    AND sg.location && ST_Transform(ST_TileEnvelope(%s, %s, %s), 4326)
            ) AS tile
            WHERE geom IS NOT NULL
            """,
            [z, x, y, z, x, y, z, x, y, z, x, y],
        )
        row = cursor.fetchone()
    mvt_data = bytes(row[0]) if row and row[0] else b""
    return HttpResponse(mvt_data, content_type="application/x-protobuf")


def stats(request):
    return JsonResponse(cache.get("vehicle-tracking-stats", []), safe=False)


@login_required
def staff_stats(request):
    if not request.user.is_staff:
        raise Http404

    usage_entries = get_site_usage_entries()
    now_ts = timezone.now().timestamp()
    windows = (
        ("5 minutes", 5 * 60),
        ("1 hour", 60 * 60),
        ("24 hours", 24 * 60 * 60),
        ("7 days", 7 * 24 * 60 * 60),
    )

    activity = []
    for label, seconds in windows:
        active_entries = [
            entry
            for entry in usage_entries.values()
            if entry.get("last_seen", 0) >= now_ts - seconds
        ]
        activity.append(
            {
                "label": label,
                "total": len(active_entries),
                "authenticated": sum(
                    1 for entry in active_entries if entry.get("authenticated")
                ),
                "anonymous": sum(
                    1 for entry in active_entries if not entry.get("authenticated")
                ),
                "staff": sum(1 for entry in active_entries if entry.get("staff")),
            }
        )

    return render(
        request,
        "staff_stats.html",
        {
            "activity": activity,
            "registered_users": User.objects.count(),
            "staff_users": User.objects.filter(is_staff=True).count(),
        },
    )


@login_required
def theme_lab(request):
    if not request.user.is_staff:
        raise Http404

    livery_presets = list(
        Livery.objects.filter(published=True)
        .order_by("name")
        .values("id", "name", "colour", "colours", "left_css", "right_css", "white_text")
    )

    return render(
        request,
        "theme_lab.html",
        {
            "livery_presets": livery_presets,
        },
    )


def timetable_source_stats(request):
    return JsonResponse(cache.get("timetable-source-stats", []), safe=False)


@cache_control(max_age=3600)
def stops_json(request):
    """JSON endpoint accessed by the JavaScript map,
    listing the active StopPoints within a rectangle,
    in standard GeoJSON format
    """
    try:
        bounding_box = get_bounding_box(request)
    except (KeyError, ValueError):
        return HttpResponseBadRequest()

    if bounding_box.area > 0.15:
        return HttpResponseBadRequest()

    include_unlinked = (
        request.user.is_staff and request.GET.get("include_unlinked") == "1"
    )
    stop_filters = {"latlong__bboverlaps": bounding_box}
    if include_unlinked:
        stop_filters["active"] = True
    else:
        stop_filters["service__current"] = True

    results = (
        StopPoint.objects.filter(**stop_filters)
        .annotate(line_names=stop_line_names)
        .select_related("locality")
        .defer("locality__latlong")
        .distinct()
    )
    groups = StopGroup.objects.filter(
        active=True,
        location__bboverlaps=bounding_box,
    )

    return JsonResponse(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": stop.latlong.coords,
                    },
                    "properties": {
                        "atco_code": stop.atco_code,
                        "name": stop.get_qualified_name(),
                        "indicator": stop.indicator,
                        "icon": stop.get_icon(),
                        "bearing": stop.get_heading(),
                        "url": stop.get_absolute_url(),
                        "services": stop.get_line_names(),
                        "stop_type": stop.stop_type,
                        "bus_stop_type": stop.bus_stop_type,
                        "stop_group": False,
                    },
                }
                for stop in results
            ]
            + [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": group.location.coords,
                    },
                    "properties": {
                        "name": group.name,
                        "indicator": "",
                        "icon": "G",
                        "bearing": None,
                        "url": group.get_absolute_url(),
                        "services": sorted(
                            line_name
                            for line_name in set(
                                Service.objects.filter(
                                    current=True,
                                    stops__stopgroupstop__group=group,
                                ).values_list("line_name", flat=True)
                            )
                            if line_name
                        ),
                        "stop_type": "GRP",
                        "bus_stop_type": "",
                        "stop_group": True,
                    },
                }
                for group in groups
                if group.location
            ],
        }
    )


def train_map(request):
    return render(request, "train_map.html")


def trains_json(request):
    if not settings.DARWIN_TRAINS_NODE_URL:
        return JsonResponse([], safe=False)

    query = request.META.get("QUERY_STRING", "")
    url = f"{settings.DARWIN_TRAINS_NODE_URL}/trains.json"
    if query:
        url = f"{url}?{query}"

    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
    except requests.RequestException:
        return JsonResponse([], safe=False, status=502)

    return HttpResponse(
        response.content,
        content_type=response.headers.get(
            "Content-Type", "application/json; charset=utf-8"
        ),
    )


class UppercasePrimaryKeyMixin:
    """Normalises the primary key argument to uppercase"""

    def get_object(self, queryset=None):
        """Given a pk argument like 'ea' or 'sndr',
        convert it to 'EA' or 'SNDR',
        then otherwise behaves like ordinary get_object
        """
        primary_key = self.kwargs.get("pk")
        if (
            primary_key is not None
            and "-" not in primary_key
            and not primary_key.isupper()
        ):
            self.kwargs["pk"] = primary_key.upper()
        return super().get_object(queryset)


class RegionDetailView(UppercasePrimaryKeyMixin, DetailView):
    """A single region and the administrative areas in it"""

    model = Region

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["areas"] = self.object.adminarea_set.exclude(name="")
        if len(context["areas"]) == 1:
            context["districts"] = (
                context["areas"][0]
                .district_set.filter(locality__stoppoint__active=True)
                .distinct()
            )
            del context["areas"]

        context["operators"] = Operator.objects.filter(
            ceased_operations_on__isnull=True,
        ).filter(
            Q(region=self.object)
            | Q(
                noc__in=Operator.regions.through.objects.filter(
                    region=self.object
                ).values("operator")
            ),
        ).only("slug", "name")

        if len(context["operators"]) == 1:
            context["services"] = sorted(
                context["operators"][0]
                .service_set.filter(current=True)
                .defer("geometry"),
                key=Service.get_order,
            )
            context["colours"] = get_colours(context["services"])

        return context


class AdminAreaDetailView(DetailView):
    """A single administrative area,
    and the districts, localities (or stops) in it
    """

    model = AdminArea
    queryset = model.objects.select_related("region")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        stops = StopPoint.objects.filter(
            Exists("service", filter=Q(service__current=True))
        )

        # Districts in this administrative area
        context["districts"] = self.object.district_set.filter(
            Exists(stops.filter(locality__district=OuterRef("pk")))
        )

        context["operators"] = Operator.objects.filter(
            ceased_operations_on__isnull=True,
        ).filter(
            Exists(
                Service.objects.filter(
                    current=True,
                    operator=OuterRef("pk"),
                    stops__admin_area=self.object,
                )
                .only("id")
                .order_by()
            )
        ).only("slug", "name")

        # Districtless localities in this administrative area
        context["localities"] = self.object.locality_set.filter(
            Exists(stops.filter(locality=OuterRef("pk")))
            | Exists(stops.filter(locality__parent=OuterRef("pk"))),
            district=None,
            parent=None,
        ).defer("latlong")

        if not (context["localities"] or context["districts"]):
            services = Service.objects.filter(current=True).defer(
                "geometry", "search_vector"
            )
            services = services.filter(
                Exists(
                    StopPoint.objects.filter(
                        service=OuterRef("pk"), admin_area=self.object
                    )
                )
            )
            context["services"] = sorted(services, key=Service.get_order)
            context["modes"] = {
                service.mode for service in context["services"] if service.mode
            }
        record_recently_viewed(
            self.request,
            item_type="operator",
            item_id=self.object.pk,
            title=self.object.name or self.object.noc,
            url=self.object.get_absolute_url(),
            subtitle=f"Operator {self.object.noc}",
        )

        context["breadcrumb"] = [self.object.region]
        return context

    def render_to_response(self, context):
        if (
            "services" not in context
            and len(context["districts"]) + len(context["localities"]) == 1
        ):
            if not context["localities"]:
                return redirect(context["districts"][0])
            return redirect(context["localities"][0])
        return super().render_to_response(context)


class DistrictDetailView(DetailView):
    """A single district, and the localities in it"""

    model = District
    queryset = model.objects.select_related("admin_area", "admin_area__region")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        stops = StopPoint.objects.filter(active=True)
        context["localities"] = self.object.locality_set.filter(
            Exists(stops.filter(locality=OuterRef("pk")))
            | Exists(stops.filter(locality__parent=OuterRef("pk"))),
        ).defer("latlong")

        context["breadcrumb"] = [self.object.admin_area.region, self.object.admin_area]

        return context

    def render_to_response(self, context):
        if len(context["localities"]) == 1:
            return redirect(context["localities"][0])
        return super().render_to_response(context)


class LocalityDetailView(UppercasePrimaryKeyMixin, DetailView):
    """A single locality, its children (if any), and the stops in it"""

    model = Locality
    queryset = model.objects.select_related(
        "admin_area", "admin_area__region", "district", "parent"
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        stops = StopPoint.objects.filter(active=True)

        has_stops = Exists(stops.filter(locality=OuterRef("pk")))
        has_stops |= Exists(stops.filter(locality__parent=OuterRef("pk")))

        context["localities"] = self.object.locality_set.filter(has_stops).defer(
            "latlong"
        )

        context["adjacent"] = Locality.objects.filter(
            has_stops, adjacent=self.object
        ).defer("latlong")

        context["stops"] = (
            self.object.stoppoint_set.filter(
                service__current=True,
            )
            .annotate(line_names=stop_line_names)
            .order_by("common_name", "indicator")
            .defer("latlong")
        )

        if not (context["localities"] or context["stops"]):
            raise Http404(
                f"Sorry, it looks like no services currently stop at {self.object}"
            )

        if context["stops"]:
            stops = [stop.pk for stop in context["stops"]]
            context["services"] = sorted(
                Service.objects.filter(
                    stops__in=stops,
                    current=True,
                )
                .annotate(operators=operator_names, line_names=stop_line_names)
                .defer("geometry", "search_vector"),
                key=Service.get_order,
            )
            context["modes"] = {
                service.mode for service in context["services"] if service.mode
            }
            context["colours"] = get_colours(context["services"])
        context["breadcrumb"] = [
            crumb
            for crumb in [
                self.object.admin_area.region,
                self.object.admin_area,
                self.object.district,
                self.object.parent,
            ]
            if crumb is not None
        ]

        return context


def get_departures_context(stop, services, form_data) -> dict:
    context = {}
    when = None
    form = forms.DeparturesForm(form_data)
    if form.is_valid():
        date = form.cleaned_data["date"]
        time = form.cleaned_data["time"]
        if time is None:
            time = datetime.time()  # 00:00
        when = datetime.datetime.combine(date, time)
    context["when"] = when

    # Check if this is a train station (has CRS code and rail-related stop type)
    is_train_station = bool(stop.crs_code) and stop.stop_type in ["RSE", "RLY", "RPL"]

    if is_train_station and not when:
        # Use train departures provider for railway stations
        from departures.sources import TrainDepartures
        train_departures = TrainDepartures(stop).get_departures()
        context["departures"] = train_departures or []
        context["is_train_station"] = True
    else:
        # Use regular bus departures logic
        departures = live.get_departures(stop, services, when)
        context.update(departures)
        context["is_train_station"] = False

    if context["departures"]:
        context["has_live"] = any(item.get("live") for item in context["departures"])
        context["has_scheduled"] = any(
            item.get("time") for item in context["departures"]
        )
    if context["when"]:
        if len(context["departures"]) < 12:
            context["next_page"] = {
                "date": context["when"].date() + datetime.timedelta(days=1),
                "time": None,
            }
        elif last_time := context["departures"][-1].get("time"):
            context["next_page"] = {
                "date": last_time.date(),
                "time": last_time.time().strftime("%H:%M"),
            }

    return context


stop_line_names = ArrayAgg("stopusage__line_name", distinct=True, default=None)
operator_names = ArrayAgg("operator__name", distinct=True, default=None)


class StopPointDetailView(DetailView):
    """A stop, other stops in the same area, and the services servicing it"""

    model = StopPoint
    queryset = model.objects.select_related(
        "admin_area",
        "admin_area__region",
        "locality",
        "locality__parent",
        "locality__district",
        "stop_area",
    ).prefetch_related("features")
    queryset = queryset.defer("locality__latlong", "locality__parent__latlong")

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return get_object_or_404(queryset, pk__iexact=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        group = (
            StopGroup.objects.filter(active=True, stops=self.object)
            .order_by("name")
            .first()
        )
        if group:
            return redirect(group)
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        services = (
            self.object.service_set.filter(current=True)
            .annotate(line_names=stop_line_names, operators=operator_names)
            .defer("geometry", "search_vector")
        )
        context["services"] = sorted(services, key=Service.get_order)

        context["breadcrumb"] = [
            self.object.get_region(),
            self.object.admin_area,
            self.object.locality and self.object.locality.district,
            self.object.locality and self.object.locality.parent,
            self.object.locality,
        ]

        if not (self.object.active or context["services"]):
            return context

        context.update(get_departures_context(self.object, services, self.request.GET))

        text = ", ".join(
            part
            for part in (
                "on " + self.object.street if self.object.street else None,
                "near " + self.object.crossing if self.object.crossing else None,
                "near " + self.object.landmark if self.object.landmark else None,
            )
            if part is not None
        )
        if text:
            context["text"] = f"{text[0].upper()}{text[1:]}"

        context["modes"] = {
            service.mode for service in context["services"] if service.mode
        }
        context["colours"] = get_colours(context["services"])

        nearby = (
            StopPoint.objects.filter(active=True)
            .order_by("common_name", "indicator")
            .filter(service__current=True)
        )

        if self.object.stop_area_id is not None:
            nearby = nearby.filter(stop_area=self.object.stop_area_id)
        elif self.object.locality or self.object.admin_area:
            nearby = nearby.filter(common_name=self.object.common_name)
            if self.object.locality:
                nearby = nearby.filter(locality=self.object.locality)
            else:
                nearby = nearby.filter(admin_area=self.object.admin_area)
                if self.object.town:
                    nearby = nearby.filter(town=self.object.town)
        else:
            nearby = None

        if nearby is not None:
            context["nearby"] = (
                nearby.exclude(pk=self.object.pk)
                .filter(service__current=True)
                .annotate(line_names=stop_line_names)
                .defer("latlong")
            )

            if (
                self.object.stop_area
                and self.object.stop_area.name
                and self.object.stop_area.stop_area_type != "GPBS"
            ):
                # stop area (if it is not an on-street pair)
                context["breadcrumb"].append(self.object.stop_area)

        if not DISRUPTIONS_AVAILABLE:
            context["situations"] = []
        else:
            try:
                consequences = Consequence.objects.filter(stops=self.object)
                context["situations"] = (
                    Situation.objects.filter(
                        publication_window__contains=Now(),
                        consequence__stops=self.object,
                        current=True,
                    )
                    .distinct()
                    .order_by("publication_window")
                    .prefetch_related(
                        Prefetch(
                            "consequence_set", queryset=consequences, to_attr="consequences"
                        ),
                        "link_set",
                        "validityperiod_set",
                    )
                )
            except Exception:
                context["situations"] = []

        return context

    def render_to_response(self, context):
        response = super().render_to_response(context)
        if not (self.object.active or context["services"]):
            response.status_code = HTTPStatus.NOT_FOUND
            patch_response_headers(response)
        return response


@login_required
def edit_stop(request, pk):
    check_user(request)

    stop = get_object_or_404(
        StopPoint.objects.select_related(
            "admin_area",
            "admin_area__region",
            "locality",
            "locality__parent",
            "locality__district",
            "stop_area",
        ).prefetch_related("features"),
        pk__iexact=pk,
    )

    form_data = ensure_vehicle_revision_rules(request, stop)
    if hasattr(form_data, "status_code"):
        return form_data

    form = forms.EditStopForm(form_data, stop=stop)
    request_entry = None
    recent_logs = DataChangeLog.objects.filter(
        source="stop_request",
        target_model="busstops.stoppoint",
        target_pk=str(stop.pk),
    ).select_related("approved_by")

    if form_data:
        if form.has_changed() is False or form.changed_data == ["summary"]:
            form.add_error(None, "You haven't changed anything")

        if form.is_valid():
            pending_exists = recent_logs.filter(status=DataChangeLog.STATUS_PENDING).exists()
            if pending_exists and not (request.user.trusted or request.user.is_superuser):
                form.add_error(None, "This stop already has a pending edit awaiting approval.")
            else:
                scalar_fields = (
                    "common_name",
                    "indicator",
                    "landmark",
                    "street",
                    "crossing",
                    "description",
                    "notes",
                )
                changes = {}
                many_to_many = {}

                for field_name in scalar_fields:
                    if field_name not in form.changed_data:
                        continue
                    current_value = getattr(stop, field_name) or ""
                    new_value = form.cleaned_data[field_name] or ""
                    changes[field_name] = {"from": current_value, "to": new_value}

                if (
                    "features" in form.changed_data
                    or "accessibility_features" in form.changed_data
                ):
                    current_features = list(stop.features.all())
                    requested_features = list(form.cleaned_data["features"]) + list(
                        form.cleaned_data["accessibility_features"]
                    )
                    changes["features"] = {
                        "from": ", ".join(str(feature) for feature in current_features),
                        "to": ", ".join(str(feature) for feature in requested_features),
                    }
                    many_to_many["features"] = [feature.pk for feature in requested_features]

                summary = form.cleaned_data["summary"]
                log = DataChangeLog.objects.create(
                    source="stop_request",
                    target_model="busstops.stoppoint",
                    target_pk=str(stop.pk),
                    target_repr=stop.get_long_name(),
                    operation="update",
                    changes=changes,
                    payload={
                        "many_to_many": many_to_many,
                        "requested_by_id": request.user.id,
                        "requested_by_label": str(request.user),
                        "requested_title": stop.get_long_name(),
                        "summary": summary,
                    },
                    status=DataChangeLog.STATUS_PENDING,
                    reason=summary,
                )

                if request.user.trusted or request.user.is_superuser:
                    from .data_changes import apply_pending_change

                    apply_pending_change(log, user=request.user)

                request_entry = wrap_request_log_for_user(log, request.user).object
                form = None

    recent_entries = [
        wrap_request_log_for_user(log, request.user)
        for log in recent_logs.filter(
            Q(status=DataChangeLog.STATUS_PENDING)
            | Q(created_at__gte=Now() - datetime.timedelta(days=7))
        ).order_by("-created_at")
    ]

    return render(
        request,
        "edit_stop.html",
        {
            "form": form,
            "object": stop,
            "stop": stop,
            "request_entry": request_entry,
            "recent_entries": recent_entries,
            "breadcrumb": [
                stop.get_region(),
                stop.admin_area,
                stop.locality and stop.locality.district,
                stop.locality and stop.locality.parent,
                stop.locality,
                stop,
            ],
        },
    )


class StopAreaDetailView(DetailView):
    model = StopArea
    queryset = model.objects.select_related(
        "admin_area",
        "admin_area__region",
    )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        stops = (
            self.object.stoppoint_set.filter(service__current=True)
            .annotate(line_names=stop_line_names)
            .order_by("common_name", "indicator")
        )
        context["children"] = stops

        services = Service.objects.filter(
            current=True, stops__stop_area=self.object
        ).annotate(line_names=stop_line_names, operators=operator_names)
        context.update(get_departures_context(self.object, services, self.request.GET))

        context["breadcrumb"] = [
            self.object.admin_area.region,
            self.object.admin_area,
            self.object.parent,
        ]

        if stops:
            for stop in stops:
                if " " in stop.indicator:
                    context["indicator_prefix"] = stop.indicator.split(" ")[
                        0
                    ].title()  # Stand, Stance, Stop
                    break
            if stop.locality:
                context["breadcrumb"] += [stop.locality.parent, stop.locality]

            stops_dict = {stop.pk: stop for stop in stops}

            for item in context["departures"]:
                item["stop_time"].stop = stops_dict[item["stop_time"].stop_id]

        return context


def stop_area_departures(request, pk):
    stop_area = get_object_or_404(StopArea, pk=pk)
    services = Service.objects.filter(current=True, stops__stop_area=stop_area).annotate(
        line_names=stop_line_names, operators=operator_names
    )
    stops = stop_area.stoppoint_set.filter(service__current=True)
    context = get_departures_context(stop_area, services, request.GET)
    context["object"] = stop_area

    if stops:
        stops_dict = {stop.pk: stop for stop in stops}
        for item in context["departures"]:
            item["stop_time"].stop = stops_dict[item["stop_time"].stop_id]

    return render(request, "departures.html", context)


def stop_departures(request, atco_code):
    stop = get_object_or_404(StopPoint, atco_code=atco_code)

    services = stop.service_set.filter(current=True).annotate(operators=operator_names)

    context = get_departures_context(stop, services, request.GET)

    context["object"] = stop

    return render(request, "departures.html", context)


def get_stop_group_departures_context(group, form_data):
    context = {}
    when = None
    form = forms.DeparturesForm(form_data)
    if form.is_valid():
        date = form.cleaned_data["date"]
        time = form.cleaned_data["time"] or datetime.time()
        when = datetime.datetime.combine(date, time)
    context["when"] = when

    departures = []
    stops = list(group.stops.filter(active=True))
    for stop in stops:
        services = stop.service_set.filter(current=True).annotate(operators=operator_names)
        stop_context = get_departures_context(stop, services, form_data)
        for item in stop_context.get("departures", []):
            item["group_stop"] = stop
            if item.get("stop_time"):
                item["stop_time"].stop = stop
            departures.append(item)

    departures.sort(key=live.get_departure_order)
    context["departures"] = departures
    now = timezone.localtime()
    context["today"] = now.date()
    context["now"] = now
    context["has_live"] = any(item.get("live") for item in departures)
    context["has_scheduled"] = any(item.get("time") for item in departures)
    context["show_stop_column"] = True
    context["indicator_prefix"] = "Stop"
    if when and departures:
        last_time = departures[-1].get("time")
        if last_time:
            context["next_page"] = {
                "date": last_time.date(),
                "time": last_time.time().strftime("%H:%M"),
            }
    return context


class StopGroupDetailView(DetailView):
    model = StopGroup

    def get_queryset(self):
        return StopGroup.objects.filter(active=True).prefetch_related("stops")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_stop_group_departures_context(self.object, self.request.GET))
        context["children"] = (
            self.object.stops.filter(active=True)
            .annotate(line_names=stop_line_names)
            .order_by("stopgroupstop__order", "common_name", "indicator")
        )
        first_stop = context["children"].first()
        if first_stop and first_stop.admin_area_id:
            context["breadcrumb"] = [
                first_stop.admin_area.region,
                first_stop.admin_area,
                first_stop.locality,
            ]
        return context


def stop_group_departures(request, slug):
    group = get_object_or_404(StopGroup, slug=slug, active=True)
    context = get_stop_group_departures_context(group, request.GET)
    context["object"] = group
    return render(request, "departures.html", context)


class OperatorDetailView(DetailView):
    "An operator and the services it operates"

    model = Operator
    queryset = model.objects.select_related(
        "organisation", "group__organisation", "region"
    )

    @staticmethod
    def get_breadcrumb(operator):
        return get_operator_breadcrumb(operator)

    def get_active_tab(self):
        if self.request.GET.get("tab") in {"blocks", "depots", "liveries", "tickets"}:
            return self.request.GET["tab"]
        return "routes"

    @staticmethod
    def _route_is_event_visible(route, today):
        if not route.start_date:
            return False
        visible_from = route.start_date
        visible_until = route.end_date or route.start_date
        return visible_from <= today <= visible_until

    def get_services_for_routes_tab(self):
        today = timezone.localdate()
        services = (
            Service.objects.with_line_names()
            .filter(operator=self.object)
            .filter(Q(current=True) | Q(non_current_route=True) | Q(event_specific=True))
            .prefetch_related(
                Prefetch(
                    "route_set",
                    queryset=Route.objects.only(
                        "id",
                        "service_id",
                        "code",
                        "start_date",
                        "end_date",
                    ),
                )
            )
            .defer("geometry", "search_vector")
        )

        visible_services = []
        non_current_services = []
        event_services = []
        for service in services:
            routes = list(service.route_set.all())
            has_visible_event_route = any(
                self._route_is_event_visible(route, today) for route in routes
            )
            if not (
                service.current
                or has_visible_event_route
                or service.non_current_route
                or service.event_specific
            ):
                continue

            route_start_dates = [route.start_date for route in routes if route.start_date]
            event_start_dates = [
                route.start_date
                for route in routes
                if self._route_is_event_visible(route, today) and route.start_date
            ]
            service.start_date = min(route_start_dates + event_start_dates, default=None)

            if self.object.name == "National Express" and any(
                "_Events-" in (route.code or "") for route in routes
            ):
                service.group = "Festival & event travel"
            else:
                service.group = ""

            if service.event_specific:
                event_services.append(service)
            elif service.non_current_route:
                non_current_services.append(service)
            else:
                visible_services.append(service)

        return visible_services, non_current_services, event_services

    def get_rail_replacement_services(self):
        rail_replacement_services = (
            Service.objects.with_line_names()
            .filter(
                operator=self.object,
                current=True,
                is_rail_replacement=True
            )
            .defer("geometry", "search_vector")
        )
        return list(rail_replacement_services)

    def get_liveries(self, vehicle_queryset):
        livery_rows = list(
            vehicle_queryset.filter(livery__isnull=False)
            .values("livery_id", "livery__name")
            .annotate(vehicle_count=Count("id"))
            .order_by("-vehicle_count", "livery__name")
        )
        liveries_by_id = Livery.objects.in_bulk([row["livery_id"] for row in livery_rows])
        liveries = []
        for row in livery_rows:
            livery = liveries_by_id.get(row["livery_id"])
            if not livery:
                continue
            livery.vehicle_count = row["vehicle_count"]
            if not livery.left_css and livery.colours:
                livery.preview_css = get_css(livery.colours.split())
            else:
                livery.preview_css = livery.left_css
            liveries.append(livery)
        return liveries

    def get_ticket_types(self):
        if not FARES_AVAILABLE:
            return []
        try:
            return group_serialized_tickets(
                [
                    *[
                        serialize_tariff_ticket(tariff)
                        for tariff in get_published_tariffs()
                        .filter(operators=self.object)
                        .distinct()
                        .order_by("name", "valid_between")
                    ],
                    *[
                        serialize_manual_ticket(ticket)
                        for ticket in get_manual_tickets()
                        .filter(operator=self.object)
                        .order_by("name", "id")
                    ],
                ],
                by_service_signature=True,
            )
        except Exception:
            return []

    def get_blocks_date(self):
        try:
            return datetime.date.fromisoformat(self.request.GET.get("date", ""))
        except (TypeError, ValueError):
            return timezone.localdate()

    def get_blocks(self, date):
        calendar_ids = get_calendars(date).values("id")
        trips = (
            Trip.objects.filter(
                operator=self.object,
                calendar_id__in=calendar_ids,
                block__isnull=False,
            )
            .exclude(block="")
            .select_related("route", "route__service", "destination", "garage")
            .order_by("block", "start", "id")
        )

        blocks = []
        by_block = {}
        for trip in trips:
            block = by_block.get(trip.block)
            if block is None:
                block = {
                    "name": trip.block,
                    "trips": [],
                    "start": trip.start,
                    "end": trip.end,
                    "garage": trip.garage,
                    "url": f"{trip.get_absolute_url()}/block?date={date.isoformat()}",
                }
                by_block[trip.block] = block
                blocks.append(block)
            block["trips"].append(trip)
            if trip.start < block["start"]:
                block["start"] = trip.start
            if trip.end > block["end"]:
                block["end"] = trip.end
            if block["garage"] != trip.garage:
                block["garage"] = None

        blocks.sort(key=lambda block: (block["start"], block["name"]))
        return blocks

    def get_object(self):
        try:
            return super().get_object()
        except Http404:
            if "slug" in self.kwargs:
                try:
                    return get_object_or_404(
                        self.queryset,
                        operatorcode__code=self.kwargs["slug"],
                        operatorcode__source__name="slug",
                    )
                except Http404:
                    self.kwargs["pk"] = self.kwargs["slug"].upper()
                    return super().get_object()
            raise

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = self.get_active_tab()
        context["active_fleet_tab"] = (
            context["active_tab"] if context["active_tab"] in {"blocks", "depots"} else ""
        )

        if not DISRUPTIONS_AVAILABLE:
            context["situations"] = []
        else:
            try:
                queryset = (
                    Situation.objects.filter(
                        Q(consequence__operators=self.object) | Q(affected_operators=self.object),
                        publication_window__contains=Now(),
                        current=True,
                    )
                    .order_by("publication_window")
                    .distinct()
                    .prefetch_related(
                        Prefetch(
                            "consequence_set",
                            queryset=Consequence.objects.filter(operators=self.object),
                            to_attr="consequences",
                        ),
                        "link_set",
                        "validityperiod_set",
                        "affected_operators",
                        "affected_services",
                        "affected_admin_areas",
                    )
                )
                # Evaluate the queryset now to catch any database errors
                context["situations"] = list(queryset)
            except Exception:
                context["situations"] = []

        # services list:

        services, non_current_services, event_services = self.get_services_for_routes_tab()
        context["services"] = sorted(services, key=Service.get_order)
        context["non_current_services"] = sorted(
            non_current_services, key=Service.get_order
        )
        context["event_services"] = sorted(event_services, key=Service.get_order)
        context["event_services_count"] = len(event_services)
        context["rail_replacement_services"] = self.get_rail_replacement_services()
        context["rail_replacement_services_count"] = len(context["rail_replacement_services"])

        if context["services"] or context["non_current_services"] or context["event_services"]:
            # for 'from {date}' for future services:
            context["today"] = timezone.localdate()
            context["colours"] = get_colours(
                context["services"] + context["non_current_services"] + context["event_services"]
            )

        record_recently_viewed(
            self.request,
            item_type="operator",
            item_id=self.object.pk,
            title=self.object.name or self.object.noc,
            url=self.object.get_absolute_url(),
            subtitle=f"Operator {self.object.noc}",
        )

        context["breadcrumb"] = self.get_breadcrumb(self.object)

        # this is a bit of a faff,
        # just to avoid doing separate queries
        # for National Operator Codes and MyTrip
        operator_codes = self.object.operatorcode_set.annotate(
            source_name=F("source__name")
        )

        context["tickets_link"] = get_operator_tickets_link(
            self.object, operator_codes
        )
        context["operator_tickets"] = self.get_ticket_types()
        context["tickets_count"] = len(context["operator_tickets"])

        context["nocs"] = [
            code.code
            for code in operator_codes
            if code.source_name == "National Operator Codes"
        ]
        context["social_links"] = get_operator_social_links(self.object)

        # vehicles tab:

        active_vehicles = self.object.vehicle_set.filter(
            **current_vehicle_filters(
                withdrawn=False,
                preserved=False,
            )
        )
        active_liveries = self.get_liveries(active_vehicles)
        context["vehicles_count"] = active_vehicles.count()
        context["vehicles"] = context["vehicles_count"] > 0
        context["liveries_count"] = len(active_liveries)
        context["liveries"] = (
            active_liveries if context["active_tab"] == "liveries" else []
        )
        context["depots_count"] = len(get_operator_depots(self.object))
        if redis_client and (
            context["vehicles"] or any(s.tracking for s in context["services"])
        ):
            try:
                context["map"] = redis_client.exists(
                    f"operator{self.object.noc}vehicles"
                )
            except ConnectionError:
                pass

        context["blocks_date"] = self.get_blocks_date()
        context["blocks"] = (
            self.get_blocks(context["blocks_date"])
            if context["active_tab"] == "blocks"
            else None
        )
        context["depots"] = []
        context["depot_map_html"] = ""
        if context["active_tab"] == "depots":
            context["depots"] = get_operator_depots(self.object)
            context["depot_map_html"] = build_depot_map_html(
                serialize_depot_map_points(context["depots"])
            )

        return context

    def render_to_response(self, context):
        status_code = None

        if (
            not context["services"]
            and not context["non_current_services"]
            and not context["vehicles"]
        ):
            alternative = Operator.objects.filter(
                operator_has_current_services,
                name=self.object.name,
            ).first()
            if alternative:
                return redirect(alternative)
            # no services or vehicles - render a 404 page that looks like a normal page
            context["ad"] = False
            status_code = HTTPStatus.NOT_FOUND

        response = super().render_to_response(context)
        if status_code:
            response.status_code = status_code
        return response


class OrganisationDetailView(DetailView):
    model = Organisation
    slug_field = "slug"
    slug_url_kwarg = "slug"
    valid_tabs = ("about", "vehicles", "operators", "garages", "liveries")

    _CHART_FALLBACK_COLORS = (
        "#3366cc",
        "#dc3912",
        "#ff9900",
        "#109618",
        "#990099",
        "#0099c6",
        "#dd4477",
        "#66aa00",
        "#b82e2e",
        "#316395",
        "#994499",
        "#22aa99",
    )

    def get_active_tab(self):
        tab = (self.request.GET.get("tab") or "about").lower()
        if tab in self.valid_tabs:
            return tab
        return "about"

    @classmethod
    def _cap_pie_series(cls, labels, data, colors, max_slices=12):
        if len(labels) <= max_slices:
            return labels, data, colors
        keep = max_slices - 1
        other = sum(data[keep:])
        return (
            labels[:keep] + ["Other"],
            data[:keep] + [other],
            colors[:keep] + ["#94a3b8"],
        )

    def _organisation_stats_charts(self, vehicle_queryset):
        """Build label/data/color lists for Chart.js doughnut charts."""
        charts = {}

        livery_rows = list(
            vehicle_queryset.values("livery_id")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if livery_rows:
            livery_ids = [r["livery_id"] for r in livery_rows if r["livery_id"]]
            liveries = Livery.objects.in_bulk(livery_ids) if livery_ids else {}
            labels, data, colors = [], [], []
            for row in livery_rows:
                lid = row["livery_id"]
                cnt = row["count"]
                data.append(cnt)
                if lid is None:
                    labels.append("No livery")
                    colors.append("#94a3b8")
                else:
                    livery = liveries.get(lid)
                    labels.append(livery.name if livery else "Unknown")
                    c = (livery.colour if livery and livery.colour else "") or "#64748b"
                    if isinstance(c, str) and c and not c.startswith("#"):
                        c = f"#{c}"
                    colors.append(c)
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["livery"] = {"labels": labels, "data": data, "colors": colors}

        vt_rows = list(
            vehicle_queryset.values("vehicle_type_id", "vehicle_type__name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if vt_rows:
            labels, data, colors = [], [], []
            for i, row in enumerate(vt_rows):
                labels.append(row["vehicle_type__name"] or "Unknown type")
                data.append(row["count"])
                colors.append(
                    self._CHART_FALLBACK_COLORS[i % len(self._CHART_FALLBACK_COLORS)]
                )
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["vehicle_type"] = {"labels": labels, "data": data, "colors": colors}

        op_rows = list(
            vehicle_queryset.values("operator_id")
            .annotate(count=Count("id"), label=Max("operator_name"))
            .order_by("-count")
        )
        if op_rows:
            labels = [r["label"] or "Operator" for r in op_rows]
            data = [r["count"] for r in op_rows]
            colors = [
                self._CHART_FALLBACK_COLORS[i % len(self._CHART_FALLBACK_COLORS)]
                for i in range(len(labels))
            ]
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["operator"] = {"labels": labels, "data": data, "colors": colors}

        grp_rows = list(
            vehicle_queryset.values("operator__group_id")
            .annotate(count=Count("id"), label=Max("operator__group__name"))
            .order_by("-count")
        )
        if grp_rows:
            labels, data, colors = [], [], []
            for i, row in enumerate(grp_rows):
                name = row["label"]
                labels.append(
                    name if name else "Direct / ungrouped"
                )
                data.append(row["count"])
                colors.append(
                    self._CHART_FALLBACK_COLORS[i % len(self._CHART_FALLBACK_COLORS)]
                )
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["group"] = {"labels": labels, "data": data, "colors": colors}

        return charts

    def get_queryset(self):
        active_operator_queryset = Operator.objects.filter(
            ceased_operations_on__isnull=True
        ).order_by("name").prefetch_related(
            Prefetch("depot_set", to_attr="ordered_depots")
        )
        ceased_operator_queryset = Operator.objects.filter(
            ceased_operations_on__isnull=False
        ).order_by("ceased_operations_on", "name")
        group_queryset = OperatorGroup.objects.order_by("name").prefetch_related(
            Prefetch(
                "operator_set",
                queryset=active_operator_queryset,
                to_attr="ordered_operators",
            ),
            Prefetch(
                "operator_set",
                queryset=ceased_operator_queryset,
                to_attr="ceased_operators",
            ),
        )
        direct_operator_queryset = active_operator_queryset.filter(group__isnull=True)
        ceased_direct_operator_queryset = ceased_operator_queryset.filter(group__isnull=True)
        return Organisation.objects.prefetch_related(
            Prefetch("operatorgroup_set", queryset=group_queryset),
            Prefetch("operator_set", queryset=direct_operator_queryset, to_attr="direct_operators"),
            Prefetch(
                "operator_set",
                queryset=ceased_direct_operator_queryset,
                to_attr="ceased_direct_operators",
            ),
        )

    def get_all_operators(self, groups, direct_operators, group_attr="ordered_operators"):
        operators = {}
        for group in groups:
            for operator in getattr(group, group_attr, ()):
                operators.setdefault(operator.pk, operator)
        for operator in direct_operators:
            operators.setdefault(operator.pk, operator)
        return list(operators.values())

    def get_vehicle_queryset(self, operators):
        operator_ids = [operator.pk for operator in operators]
        if not operator_ids:
            return Vehicle.objects.none()
        return apply_vehicle_schema_compat(
            Vehicle.objects.filter(
                **current_vehicle_filters(
                    operator_id__in=operator_ids,
                    withdrawn=False,
                    preserved=False,
                )
            )
            .annotate(
                livery_name=Case(
                    When(livery__show_name=True, then=F("livery__name")),
                    default=Value(""),
                ),
                vehicle_type_name=Coalesce(F("vehicle_type__name"), Value("")),
                garage_name=Case(
                    When(garage__name="", then=F("garage__code")),
                    default=Coalesce(F("garage__name"), Value("")),
                ),
                operator_name=Case(
                    When(operator__aka="", then=F("operator__name")),
                    default=Coalesce(F("operator__aka"), F("operator__name")),
                ),
            )
            .select_related("operator", "livery", "vehicle_type", "garage")
            .order_by("fleet_number", "fleet_code", "reg", "code", "operator__name")
        )

    def get_livery_styles(self, liveries):
        return "".join(
            style
            for livery in liveries
            for style in livery.get_styles()
        )

    def get_liveries(self, vehicle_queryset):
        livery_rows = list(
            vehicle_queryset.filter(livery__isnull=False)
            .values("livery_id", "livery__name")
            .annotate(vehicle_count=Count("id"))
            .order_by("-vehicle_count", "livery__name")
        )
        liveries_by_id = Livery.objects.in_bulk([row["livery_id"] for row in livery_rows])
        liveries = []
        for row in livery_rows:
            livery = liveries_by_id.get(row["livery_id"])
            if not livery:
                continue
            livery.vehicle_count = row["vehicle_count"]
            if not livery.left_css and livery.colours:
                livery.preview_css = get_css(livery.colours.split())
            else:
                livery.preview_css = livery.left_css
            liveries.append(livery)
        return liveries

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_tab = self.get_active_tab()
        groups = list(self.object.operatorgroup_set.all())
        direct_operators = list(getattr(self.object, "direct_operators", ()))
        ceased_direct_operators = list(getattr(self.object, "ceased_direct_operators", ()))
        organisation_operators = self.get_all_operators(groups, direct_operators)
        ceased_operators = self.get_all_operators(
            groups,
            ceased_direct_operators,
            group_attr="ceased_operators",
        )
        depots = get_organisation_depots(groups, direct_operators)
        vehicle_queryset = self.get_vehicle_queryset(organisation_operators)

        # Get all vehicles for the vehicles tab (no pagination)
        vehicles_list = None
        if active_tab == "vehicles":
            vehicles_list = list(vehicle_queryset)

        # Get liveries for the liveries tab and vehicles tab
        liveries = []
        if active_tab in ["liveries", "vehicles"]:
            liveries = self.get_liveries(vehicle_queryset)

        context["active_tab"] = active_tab
        context["groups"] = groups
        context["direct_operators"] = direct_operators
        context["ceased_direct_operators"] = ceased_direct_operators
        context["organisation_operators"] = organisation_operators
        context["ceased_operators"] = ceased_operators
        context["operators_count"] = len(organisation_operators)
        context["ceased_operators_count"] = len(ceased_operators)
        context["vehicles_count"] = vehicle_queryset.count()
        context["vehicles"] = vehicles_list
        context["liveries"] = liveries
        context["liveries_count"] = len(liveries)
        context["livery_styles"] = self.get_livery_styles(liveries) if active_tab in ["liveries", "vehicles"] else ""
        context["depots"] = depots
        context["depots_count"] = len(depots)
        context["depot_map_points"] = serialize_depot_map_points(depots) if active_tab == "garages" else []
        context["depot_map_html"] = build_depot_map_html(context["depot_map_points"])
        context["page_theme"] = get_theme_source(self.object)
        context["social_links"] = [
            ("Website", self.object.website),
            ("X", self.object.social_x),
            ("Facebook", self.object.social_fb),
            ("Instagram", self.object.social_instagram),
            ("LinkedIn", self.object.social_linkedin),
            ("YouTube", self.object.social_youtube),
            ("TikTok", self.object.social_tiktok),
            ("Threads", self.object.social_threads),
            ("Bluesky", self.object.social_bluesky),
            ("Mastodon", self.object.social_mastodon),
            ("More", self.object.social_other),
        ]
        return context


class ManufacturerDetailView(DetailView):
    model = Manufacturer
    slug_field = "slug"
    slug_url_kwarg = "slug"
    valid_tabs = ("models", "sites", "stats", "fleet")
    _CHART_FALLBACK_COLORS = OrganisationDetailView._CHART_FALLBACK_COLORS

    def get_active_tab(self):
        tab = (self.request.GET.get("tab") or "models").lower()
        if tab in self.valid_tabs:
            return tab
        return "models"

    def get_vehicle_queryset(self):
        return apply_vehicle_schema_compat(
            Vehicle.objects.filter(
                vehicle_type__manufacturer=self.object,
                **current_vehicle_filters(
                    withdrawn=False,
                    preserved=False,
                ),
            )
            .annotate(
                vehicle_type_name=Coalesce(F("vehicle_type__name"), Value("")),
                garage_name=Case(
                    When(garage__name="", then=F("garage__code")),
                    default=Coalesce(F("garage__name"), Value("")),
                ),
                operator_name=Case(
                    When(operator__aka="", then=F("operator__name")),
                    default=Coalesce(F("operator__aka"), F("operator__name"), Value("")),
                ),
            )
            .select_related("operator", "vehicle_type", "garage", "livery")
            .order_by("vehicle_type__name", "fleet_number", "fleet_code", "reg", "code")
        )

    def get_demonstrator_queryset(self, vehicles):
        return vehicles.filter(demonstrator=True)

    def get_preserved_vehicle_queryset(self):
        return apply_vehicle_schema_compat(
            Vehicle.objects.filter(
                vehicle_type__manufacturer=self.object,
                **current_vehicle_filters(
                    withdrawn=False,
                    preserved=True,
                ),
            )
        )

    def get_vehicle_groups(self, vehicles, demonstrators):
        model_counts = dict(vehicles.values_list("vehicle_type_id").annotate(count=Count("id")))
        demonstrator_counts = dict(
            demonstrators.values_list("vehicle_type_id").annotate(count=Count("id"))
        )
        preserved_counts = dict(
            self.get_preserved_vehicle_queryset()
            .values_list("vehicle_type_id")
            .annotate(count=Count("id"))
        )
        all_types = list(
            VehicleType.objects.filter(manufacturer=self.object)
            .select_related("vehicle_group")
            .order_by("name")
        )
        groups = []
        group_map = {}

        for vehicle_type in all_types:
            vehicle_type.active_vehicle_count = model_counts.get(vehicle_type.id, 0)
            vehicle_type.demonstrator_count = demonstrator_counts.get(vehicle_type.id, 0)
            vehicle_type.preserved_vehicle_count = preserved_counts.get(vehicle_type.id, 0)
            vehicle_type.existing_vehicle_count = (
                vehicle_type.active_vehicle_count + vehicle_type.preserved_vehicle_count
            )
            group = vehicle_type.vehicle_group
            group_key = group.id if group else f"ungrouped-{vehicle_type.id}"
            group_name = group.name if group else vehicle_type.name
            group_entry = group_map.get(group_key)
            if group_entry is None:
                group_entry = {
                    "group": group,
                    "name": group_name,
                    "vehicle_types": [],
                    "vehicle_count": 0,
                    "demonstrator_count": 0,
                    "preserved_vehicle_count": 0,
                    "in_production_count": 0,
                }
                group_map[group_key] = group_entry
                groups.append(group_entry)

            group_entry["vehicle_types"].append(vehicle_type)
            group_entry["vehicle_count"] += vehicle_type.active_vehicle_count
            group_entry["demonstrator_count"] += vehicle_type.demonstrator_count
            group_entry["preserved_vehicle_count"] += vehicle_type.preserved_vehicle_count
            if vehicle_type.active_production:
                group_entry["in_production_count"] += 1

        return groups

    @classmethod
    def _cap_pie_series(cls, labels, data, colors, max_slices=12):
        return OrganisationDetailView._cap_pie_series(labels, data, colors, max_slices)

    def get_stats_charts(self, vehicles):
        charts = {}
        style_choices = dict(VehicleType._meta.get_field("style").choices)
        fuel_choices = dict(VehicleType._meta.get_field("fuel").choices)

        style_rows = list(
            vehicles.values("vehicle_type__style")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if style_rows:
            labels = [
                style_choices.get(row["vehicle_type__style"]) or "Unknown style"
                for row in style_rows
            ]
            data = [row["count"] for row in style_rows]
            colors = [
                self._CHART_FALLBACK_COLORS[i % len(self._CHART_FALLBACK_COLORS)]
                for i in range(len(labels))
            ]
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["style"] = {"labels": labels, "data": data, "colors": colors}

        fuel_rows = list(
            vehicles.values("vehicle_type__fuel")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        if fuel_rows:
            labels = [
                fuel_choices.get(row["vehicle_type__fuel"]) or "Unknown fuel"
                for row in fuel_rows
            ]
            data = [row["count"] for row in fuel_rows]
            colors = [
                self._CHART_FALLBACK_COLORS[i % len(self._CHART_FALLBACK_COLORS)]
                for i in range(len(labels))
            ]
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["fuel"] = {"labels": labels, "data": data, "colors": colors}

        operator_rows = list(
            vehicles.values("operator_id")
            .annotate(count=Count("id"), label=Max("operator_name"))
            .order_by("-count")
        )
        if operator_rows:
            labels = [row["label"] or "Manufacturer-owned / unallocated" for row in operator_rows]
            data = [row["count"] for row in operator_rows]
            colors = [
                self._CHART_FALLBACK_COLORS[i % len(self._CHART_FALLBACK_COLORS)]
                for i in range(len(labels))
            ]
            labels, data, colors = self._cap_pie_series(labels, data, colors)
            charts["operator"] = {"labels": labels, "data": data, "colors": colors}

        return charts

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_tab = self.get_active_tab()
        vehicles = self.get_vehicle_queryset()
        demonstrators = self.get_demonstrator_queryset(vehicles)
        vehicle_groups = self.get_vehicle_groups(vehicles, demonstrators)
        sites = get_manufacturer_sites(self.object)

        fleet_page = None
        if active_tab == "fleet":
            fleet_page = Paginator(demonstrators, 100).get_page(self.request.GET.get("page"))

        context["active_tab"] = active_tab
        context["breadcrumb"] = [self.object]
        context["page_theme"] = get_theme_source(self.object)
        context["vehicle_groups"] = vehicle_groups
        context["vehicle_types_count"] = sum(
            len(group["vehicle_types"]) for group in vehicle_groups
        )
        context["vehicle_group_count"] = len(vehicle_groups)
        context["vehicles_count"] = vehicles.count()
        context["demonstrator_count"] = demonstrators.count()
        context["fleet"] = fleet_page
        context["sites"] = sites
        context["sites_count"] = len(sites)
        context["site_map_points"] = serialize_depot_map_points(sites) if active_tab == "sites" else []
        context["site_map_html"] = build_depot_map_html(context["site_map_points"])
        context["stats_charts"] = self.get_stats_charts(vehicles) if active_tab == "stats" else {}
        context["social_links"] = [
            ("Website", self.object.website),
            ("X", self.object.social_x),
            ("Facebook", self.object.social_fb),
            ("Instagram", self.object.social_instagram),
            ("LinkedIn", self.object.social_linkedin),
            ("YouTube", self.object.social_youtube),
            ("TikTok", self.object.social_tiktok),
            ("Threads", self.object.social_threads),
            ("Bluesky", self.object.social_bluesky),
            ("Mastodon", self.object.social_mastodon),
            ("More", self.object.social_other),
        ]
        return context


def preservation_group_list(request):
    groups = PreservationGroup.objects.annotate(
        vehicle_count=Count("preserved_vehicles")
    ).order_by("name")
    paginator = Paginator(groups, 24)
    return render(
        request,
        "busstops/preservation_group_list.html",
        {"groups": paginator.get_page(request.GET.get("page"))},
    )


def operator_list(request):
    operators = Operator.objects.annotate(
        vehicle_count=Count("vehicle")
    ).order_by("name")
    paginator = Paginator(operators, 48)
    return render(
        request,
        "busstops/operator_list.html",
        {"operators": paginator.get_page(request.GET.get("page"))},
    )


def government_authority_list(request):
    authorities = GovernmentAuthority.objects.order_by("name")
    paginator = Paginator(authorities, 24)
    return render(
        request,
        "busstops/government_authority_list.html",
        {"authorities": paginator.get_page(request.GET.get("page"))},
    )


def government_authority_detail(request, slug):
    authority = get_object_or_404(GovernmentAuthority, slug=slug)
    social_links = [
        ("Website", authority.website),
        ("X", authority.social_x),
        ("Facebook", authority.social_fb),
        ("Instagram", authority.social_instagram),
        ("LinkedIn", authority.social_linkedin),
        ("YouTube", authority.social_youtube),
        ("TikTok", authority.social_tiktok),
        ("Threads", authority.social_threads),
        ("Bluesky", authority.social_bluesky),
        ("Mastodon", authority.social_mastodon),
        ("More", authority.social_other),
    ]
    return render(
        request,
        "busstops/government_authority_detail.html",
        {"object": authority, "social_links": social_links, "active_tab": "about"},
    )


def government_authority_vehicles(request, slug):
    authority = get_object_or_404(GovernmentAuthority, slug=slug)
    operators = Operator.objects.filter(government_authority=authority)
    vehicles = Vehicle.objects.filter(
        operator__in=operators,
        **current_vehicle_filters(withdrawn=False, preserved=False)
    ).select_related("vehicle_type", "livery")
    
    # Get vehicle types with counts
    vehicle_types = (
        vehicles.values("vehicle_type__name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    
    # Get liveries with counts
    liveries = (
        vehicles.filter(livery__isnull=False)
        .values("livery_id", "livery__name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    
    # Get livery styles
    livery_ids = [row["livery_id"] for row in liveries]
    livery_styles = ""
    if livery_ids:
        liveries_with_styles = Livery.objects.filter(id__in=livery_ids)
        livery_styles = "".join(style for livery in liveries_with_styles for style in livery.get_styles())
    
    return render(
        request,
        "busstops/government_authority_vehicles.html",
        {
            "object": authority,
            "active_tab": "vehicles",
            "vehicle_types": vehicle_types,
            "liveries": liveries,
            "livery_styles": livery_styles,
        },
    )


def government_authority_routes(request, slug):
    authority = get_object_or_404(GovernmentAuthority, slug=slug)
    operators = Operator.objects.filter(government_authority=authority)
    services = Service.objects.filter(operator__in=operators).order_by("line_name")
    
    return render(
        request,
        "busstops/government_authority_routes.html",
        {"object": authority, "active_tab": "routes", "services": services},
    )


def government_authority_operators(request, slug):
    authority = get_object_or_404(GovernmentAuthority, slug=slug)
    operators = Operator.objects.filter(government_authority=authority).order_by("name")
    
    return render(
        request,
        "busstops/government_authority_operators.html",
        {"object": authority, "active_tab": "operators", "operators": operators},
    )


def preservation_group_detail(request, slug):
    group = get_object_or_404(
        PreservationGroup.objects.annotate(vehicle_count=Count("preserved_vehicles")),
        slug=slug,
    )
    vehicles = apply_vehicle_schema_compat(
        group.preserved_vehicles.select_related(
            "operator", "vehicle_type", "livery", "garage", "preserved_by_user"
        )
        .annotate(
            livery_name=Case(When(livery__show_name=True, then=F("livery__name"))),
            vehicle_type_name=Coalesce(F("vehicle_type__name"), Value("")),
            garage_name=Case(
                When(garage__name="", then=F("garage__code")),
                default=Coalesce(F("garage__name"), Value("")),
            ),
        )
        .order_by("operator__name", "fleet_number", "fleet_code", "reg", "code")
    )
    vehicles = Paginator(vehicles, 100).get_page(request.GET.get("page"))
    
    # Get liveries and generate CSS styles
    livery_rows = list(
        group.preserved_vehicles.filter(livery__isnull=False)
        .values("livery_id")
        .distinct()
    )
    liveries = []
    if livery_rows:
        livery_ids = [row["livery_id"] for row in livery_rows]
        liveries = list(Livery.objects.filter(id__in=livery_ids))
    livery_styles = "".join(style for livery in liveries for style in livery.get_styles())
    
    social_links = [
        ("Website", group.website),
        ("X", group.social_x),
        ("Facebook", group.social_fb),
        ("Instagram", group.social_instagram),
        ("LinkedIn", group.social_linkedin),
        ("YouTube", group.social_youtube),
        ("TikTok", group.social_tiktok),
        ("Threads", group.social_threads),
        ("Bluesky", group.social_bluesky),
        ("Mastodon", group.social_mastodon),
        ("More", group.social_other),
    ]
    return render(
        request,
        "busstops/preservation_group_detail.html",
        {
            "object": group,
            "vehicles": vehicles,
            "social_links": social_links,
            "breadcrumb": [group],
            "livery_styles": livery_styles,
        },
    )


def organisation_map(request, slug):
    organisation = get_object_or_404(
        Organisation.objects.prefetch_related(
            Prefetch(
                "operatorgroup_set",
                queryset=OperatorGroup.objects.order_by("name").prefetch_related(
                    Prefetch(
                        "operator_set",
                        queryset=Operator.objects.filter(
                            ceased_operations_on__isnull=True
                        ).order_by("name"),
                        to_attr="ordered_operators",
                    )
                ),
            ),
            Prefetch(
                "operator_set",
                queryset=Operator.objects.filter(
                    group__isnull=True,
                    ceased_operations_on__isnull=True,
                ).order_by("name"),
                to_attr="direct_operators",
            ),
        ),
        slug=slug,
    )
    operators = {}
    for group in organisation.operatorgroup_set.all():
        for operator in getattr(group, "ordered_operators", ()):
            operators.setdefault(operator.pk, operator)
    for operator in getattr(organisation, "direct_operators", ()):
        operators.setdefault(operator.pk, operator)

    operator_ids = ",".join(str(operator_id) for operator_id in operators)
    return render(
        request,
        "busstops/organisation_map.html",
        {
            "object": organisation,
            "organisation": organisation,
            "operator_ids": operator_ids,
            "map_url": reverse("organisation_map", args=(organisation.slug,)),
            "breadcrumb": [organisation],
        },
    )


class ServiceDetailView(DetailView):
    "A service and the stops it stops at"

    model = Service
    queryset = (
        model.objects.with_line_names()
        .select_related("region", "source", "colour")
        .annotate(actual_public_use=Coalesce("public_use", BoolOr("route__public_use")))
        .prefetch_related("operator")
        .defer("search_vector")
    )

    def get_object(self):
        services = Service.objects

        try:
            service = super().get_object()
        except Http404 as e:
            slug = self.kwargs["slug"]

            service = services.filter(service_code=slug).first()

            if not service:
                service = services.filter(
                    servicecode__scheme="slug", servicecode__code=slug
                ).first()

            if not service:
                service = services.filter(
                    servicecode__scheme=BUSTIMES_SLUG_SCHEME, servicecode__code=slug
                ).first()

            if not service:
                service = services.filter(
                    servicecode__scheme="ServiceCode", servicecode__code=slug
                ).first()

            if not service:
                raise e

        if not service.current:
            alternative = None

            services = services.only("slug", "current").filter(current=True)
            operators = service.operator.all()

            if service.line_name:
                if operators:
                    alternative = services.filter(
                        line_name__iexact=service.line_name,
                        operator__in=operators,
                        stops__service=service,
                    ).first()
                if not alternative:
                    alternative = services.filter(
                        line_name__iexact=service.line_name,
                        stops__service=service,
                    ).first()
                if not alternative and operators:
                    alternative = services.filter(
                        line_name__iexact=service.line_name,
                        operator__in=service.operator.all(),
                    ).first()

            if not alternative and service.description:
                alternative = services.filter(description=service.description).first()

            if not alternative and operators:
                alternative = operators[0]

            if alternative:
                return alternative

            raise Http404()

        return service

    def get_fare_tables(self):
        fare_tables = (
            FareTable.objects.filter(
                tariff__services=self.object,
                tariff__source__published=True,
            )
            .select_related("tariff", "user_profile", "sales_offer_package")
            .order_by("tariff")
        )
        if fare_tables:
            for table in fare_tables:
                table.tariff.name = (
                    table.tariff.name.removesuffix(" fares")
                    .replace(" Conc ", " Concession ")
                    .replace(" YP ", " Young Person ")
                    .replace(" Ch ", " Child ")
                    .replace("_", " ")
                    .replace(" AD ", " Adult ")
                )

            if not all(
                table.user_profile == fare_tables[0].user_profile
                for table in fare_tables[1:]
            ):
                for table in fare_tables:
                    table.tariff.name = f"{table.tariff.name} - {table.user_profile} {table.tariff.trip_type}"
            if not all(
                table.sales_offer_package == fare_tables[0].sales_offer_package
                for table in fare_tables[1:]
            ):
                for table in fare_tables:
                    table.tariff.name = (
                        f"{table.tariff.name} - {table.sales_offer_package}"
                    )

            if not all(
                table.tariff.name == fare_tables[0].tariff.name
                for table in fare_tables[1:]
            ):
                parts = fare_tables[0].tariff.name.split()
                while all(
                    table.tariff.name.startswith(f"{parts[0]} ")
                    for table in fare_tables
                ):
                    for table in fare_tables:
                        table.tariff.name = table.tariff.name.removeprefix(
                            f"{parts[0]} "
                        )
                    parts = parts[1:]
            return fare_tables

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if (
            type(self.object) is not self.model
            or self.object.slug != self.kwargs["slug"]
        ):
            return {"redirect_to": self.object}

        operators = self.object.operator.all()
        context["operators"] = operators

        context["related"] = self.object.get_similar_services()
        if context["related"]:
            context["colours"] = get_colours(
                [
                    service
                    for service in context["related"]
                    if service.colour_id != self.object.colour_id
                ]
            )

        # timetable

        date = None

        if not self.object.timetable_wrong:
            form = forms.TimetableForm(
                self.request.GET or None,
                service=self.object,
                related=context["related"],
            )

            context["timetable"] = form.get_timetable(self.object)

            context["form"] = form

            if form.is_valid():
                date = form.cleaned_data.get("date")

                # date in past - redirect to today?
                if (
                    date
                    and not (
                        context["timetable"].calendars
                        and context["timetable"].calendar_ids
                    )
                    and date < timezone.localdate()
                    and not form.cleaned_data["detailed"]
                ):
                    return {"redirect_to": self.object}

            context["registrations"] = []

        if self.object.tracking and self.object.vehiclejourney_set.exists():
            context["vehicles"] = True
            if redis_client:
                context["tracking_count"] = redis_client.scard(
                    f"service{self.object.id}vehicles"
                )

        # disruptions

        if not DISRUPTIONS_AVAILABLE:
            context["situations"] = []
        else:
            context["situations"] = (
                get_service_situations(self.object, operators)
                .prefetch_related("link_set")
                .defer("data")
            )
        stop_situations = build_stop_situations(
            context["situations"], when=date or timezone.localdate()
        )

        # mark disrupted stops in the timetable (applied lazily when rendered)
        apply_stop_situations(context.get("timetable"), stop_situations)

        def get_stopusages():
            stopusages = list(
                self.object.stopusage_set.select_related("stop__locality").defer(
                    "stop__latlong", "stop__locality__latlong"
                )
            )
            # don't bother marking individual stops if they're all disrupted
            if stop_situations and len(stop_situations) < len(stopusages):
                for stop_usage in stopusages:
                    situation = stop_situations.get(stop_usage.stop_id)
                    if situation:
                        stop_usage.situation = True
            return stopusages

        context["stopusages"] = SimpleLazyObject(get_stopusages)
        context["has_minor_stops"] = SimpleLazyObject(
            lambda: (
                not all(stop_usage.timing_point for stop_usage in context["stopusages"])
            )
        )

        try:
            context["breadcrumb"] = [
                Region.objects.filter(adminarea__stoppoint__service=self.object)
                .distinct()
                .get()
            ]
        except (Region.DoesNotExist, Region.MultipleObjectsReturned):
            context["breadcrumb"] = [self.object.region]

        context["links"] = []

        if operators:
            operator = operators[0]
            context["breadcrumb"].append(operator)
            context["payment_methods"] = []

            if operator.operatorcode_set.filter(source__name="MyTrip").exists():
                context["app"] = {
                    "url": reverse("operator_tickets", kwargs={"slug": operator.slug}),
                    "name": "MyTrip app",
                }
            for method in PaymentMethod.objects.filter(
                Exists(
                    Service.payment_methods.through.objects.filter(
                        payment_method=OuterRef("id"),
                        service=self.object,
                        accepted=True,
                    )
                )
                | Exists(
                    Operator.payment_methods.through.objects.filter(
                        paymentmethod=OuterRef("id"),
                        operator=operator,
                    )
                ),
                ~Exists(
                    Service.payment_methods.through.objects.filter(
                        payment_method=OuterRef("id"),
                        service=self.object,
                        accepted=False,
                    )
                ),
            ):
                if "app" in method.name and method.url:
                    context["app"] = method
                else:
                    context["payment_methods"].append(method)
            for operator in operators:
                if operator.name == "National Express":
                    context["tickets_link"] = (
                        f"https://nationalexpress.prf.hn/click/camref:1011ljPYw/pubref:{self.object.line_name}"
                    )
                    context["links"].append(
                        {
                            "url": context["tickets_link"],
                            "text": "Buy tickets at National Express",
                        }
                    )
                    break
                elif operator.name == "Flibco":
                    context["tickets_link"] = flibco_affiliate_link()
                    context["links"].append(
                        {
                            "url": context["tickets_link"],
                            "text": "Buy tickets at Flibco",
                        }
                    )
                    break
                elif (
                    operator.name == "FlixBus"
                    or self.object.service_code == "PF0000508:488"
                ):
                    query = {"clickref": self.object.line_name}
                    if context["breadcrumb"][0] and context["breadcrumb"][0].name == "Scotland":
                        query["ued"] = "https://www.flixbus.co.uk/scotland"
                    elif self.object.service_code == "PF0000508:488":  # Green Line 757
                        query["ued"] = (
                            "https://www.flixbus.co.uk/coach/london-luton-airport"
                        )
                    context["tickets_link"] = flixbus_affiliate_link(**query)
                    context["links"].append(
                        {
                            "url": context["tickets_link"],
                            "text": "Buy tickets at FlixBus",
                        }
                    )
                    break
        context["fare_tables"] = self.get_fare_tables()

        for url, text in self.object.get_traveline_links(date):
            context["links"].append({"url": url, "text": text})

        return context

    def render_to_response(self, context):
        if "redirect_to" in context:
            return redirect(
                context["redirect_to"],
                permanent=(type(context["redirect_to"]) is self.model),
            )
        return super().render_to_response(context)


class RouteNoticeDetailView(DetailView):
    model = RouteNotice

    def get_queryset(self):
        return RouteNotice.objects.select_related("service").prefetch_related(
            "service__operator", "other_services"
        )

    def get_object(self, queryset=None):
        queryset = queryset or self.get_queryset()
        return get_object_or_404(
            queryset,
            pk=self.kwargs["pk"],
            service__slug=self.kwargs["slug"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["breadcrumb"] = [self.object.service, self.object]
        return context


def service_timetable(request, service_id):
    services = Service.objects.with_line_names().defer("geometry", "search_vector")
    service = get_object_or_404(services, id=service_id)
    related_options = service.get_similar_services()
    form = forms.TimetableForm(request.GET, service=service, related=related_options)

    context = {
        "object": service,
        "timetable": form.get_timetable(service),
        "related": related_options,
        "form": form,
    }

    return render(request, "timetable.html", context)


def service_timetable_csv(request, service_id):
    services = Service.objects.with_line_names().defer("geometry", "search_vector")
    service = get_object_or_404(services, id=service_id)
    form = forms.TimetableForm(request.GET, service=service, related=None)

    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={service.slug}.csv"},
    )
    writer = csv.writer(response)

    for grouping in form.get_timetable(service).render().groupings:
        writer.writerow(
            ["stop", "NaPTAN code", "ATCO code"]
            + [trip.route.line_name for trip in grouping.trips]
        )
        for row in grouping.rows:
            if type(row.stop) is StopPoint:
                stop = [
                    row.stop.get_qualified_name(),
                    row.stop.naptan_code,
                    row.stop.atco_code,
                ]
            else:
                stop = [
                    str(row.stop),
                    "",
                    "",
                ]
            writer.writerow(stop + row.times)
        writer.writerow(())
    return response


def service_block_detail(request, slug, block):
    service = get_object_or_404(
        Service.objects.with_line_names().prefetch_related("operator"),
        slug=slug,
        current=True,
    )
    date = timezone.localdate()
    trip = (
        Trip.objects.filter(route__service=service, block=block)
        .exclude(block="")
        .select_related("operator", "route", "route__source", "garage", "calendar")
        .order_by("start", "id")
        .first()
    )
    if not trip:
        raise Http404

    trips = (
        get_other_trips_in_block(trip, date)
        .annotate(
            destination_name=Coalesce(
                "headsign",
                "destination__locality__name",
                "destination__common_name",
            )
        )
        .select_related("route", "destination", "operator")
    )
    trips = list(trips)
    if trips:
        prefetch_related_objects(
            trips,
            Prefetch(
                "vehiclejourney_set",
                VehicleJourney.objects.filter(date=date).select_related("vehicle"),
                to_attr="vehicle_journeys",
            ),
        )

    operators = list(service.operator.all())
    breadcrumb = []
    if trip.operator:
        breadcrumb.append(trip.operator)
    elif operators:
        breadcrumb.append(operators[0])
    breadcrumb.append(service)

    return render(
        request,
        "service_block_detail.html",
        {
            "object": block,
            "service": service,
            "operators": operators,
            "breadcrumb": breadcrumb,
            "date": date,
            "trips": trips,
            "trip": trip,
        },
    )


def service_last_modified(request, service_id):
    service = get_object_or_404(
        Service.objects.only("geometry", "line_name", "service_code", "modified_at"),
        id=service_id,
    )
    request.service = service
    return service.modified_at


@last_modified(service_last_modified)
@cdn_cache_control(max_age=3600)
def service_map_data(request, service_id):
    service = request.service
    stop_usages = list(
        service.stopusage_set.select_related("stop", "stop__locality")
        .filter(stop__latlong__isnull=False)
        .order_by("line_name", "inbound", "order", "id")
    )
    if stop_usages:
        stops = {}
        for stop_usage in stop_usages:
            stop = stop_usage.stop
            if stop.atco_code not in stops:
                stops[stop.atco_code] = stop
                stop.line_names = []
            if stop_usage.line_name and stop_usage.line_name not in stop.line_names:
                stop.line_names.append(stop_usage.line_name)
    else:
        stops = service.stops.filter(
            #     ~Exists(
            #         Situation.objects.filter(
            #             summary="Does not stop here",
            #             consequence__stops=OuterRef("pk"),
            #             consequence__services=service,
            #         )
            #     ),
            latlong__isnull=False,
        ).annotate(line_names=stop_line_names)
        stops = stops.distinct().order_by().select_related("locality").in_bulk()
    data = {
        "stops": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": stop.latlong.coords,
                    },
                    "properties": {
                        "name": stop.get_qualified_name(),
                        "bearing": stop.get_heading(),
                        "url": stop.get_absolute_url(),
                        "services": stop.line_names if hasattr(stop, "line_names") else [],
                    },
                }
                for stop in stops.values()
            ],
        },
    }

    if service.geometry and service.geometry.geom_type[-10:] == "LineString":
        data["geometry"] = {
            "type": service.geometry.geom_type,
            "coordinates": service.geometry.coords,
        }
    else:
        route_links = {
            (route_link.from_stop_id, route_link.to_stop_id): route_link
            for route_link in service.routelink_set.all()
        }

        stop_times = (
            StopTime.objects.filter(trip__route__service=service)
            .order_by("trip_id", "id")
            .values_list("trip_id", "stop_id")
        )

        multi_line_string = []
        seen_lines = set()

        for _, group in groupby(stop_times, key=lambda x: x[0]):
            line_string = []
            previous_stop_id = None
            for _, stop_id in group:
                if previous_stop_id:
                    pair = (previous_stop_id, stop_id)
                    if pair in route_links:
                        coords = route_links[pair].geometry.coords
                    elif previous_stop_id in stops and stop_id in stops:
                        origin = stops[previous_stop_id]
                        destination = stops[stop_id]
                        if origin.latlong and destination.latlong:
                            coords = [
                                origin.latlong.coords,
                                destination.latlong.coords,
                            ]
                        else:
                            coords = []
                    else:
                        coords = []

                    if coords:
                        if line_string and line_string[-1] == coords[0]:
                            line_string.extend(coords[1:])
                        else:
                            if len(line_string) > 1:
                                key = tuple(line_string)
                                if key not in seen_lines:
                                    seen_lines.add(key)
                                    multi_line_string.append(line_string)
                            line_string = list(coords)
                previous_stop_id = stop_id

            if len(line_string) > 1:
                key = tuple(line_string)
                if key not in seen_lines:
                    seen_lines.add(key)
                    multi_line_string.append(line_string)

        if not multi_line_string:
            fallback_lines = {}
            for segment in _route_editor_segments(service):
                key = (segment["line_name"], segment["inbound"])
                line = fallback_lines.setdefault(key, [])
                coords = segment["coordinates"]
                if not coords:
                    continue
                if line and line[-1] == coords[0]:
                    line.extend(coords[1:])
                elif not line:
                    line.extend(coords)
                else:
                    line.extend(coords)

            for line in fallback_lines.values():
                if len(line) > 1:
                    key = tuple(tuple(coord) for coord in line)
                    if key not in seen_lines:
                        seen_lines.add(key)
                        multi_line_string.append(line)

        data["geometry"] = {"type": "MultiLineString", "coordinates": multi_line_string}

    if has_route_geometry(data):
        return JsonResponse(data)

    bustimes_map_data = get_bustimes_service_map_data(service)
    if bustimes_map_data:
        return JsonResponse(bustimes_map_data)

    return JsonResponse(data)


def _require_route_editor_staff(request):
    if not request.user.is_staff:
        raise Http404


def _route_editor_service_queryset():
    return (
        Service.objects.with_line_names()
        .filter(current=True)
        .prefetch_related("operator")
        .defer("geometry", "search_vector")
    )


def _route_editor_stop_name(stop):
    if stop is None:
        return ""
    return stop.get_qualified_name()


def _route_editor_segments(service):
    stop_usages = list(
        service.stopusage_set.select_related("stop", "stop__locality")
        .filter(stop__latlong__isnull=False)
        .order_by("line_name", "inbound", "order", "id")
    )
    route_links = {
        (route_link.from_stop_id, route_link.to_stop_id): route_link
        for route_link in service.routelink_set.select_related("from_stop", "to_stop").prefetch_related("waypoints")
    }

    segments = []
    seen_pairs = set()

    grouped_keys = []
    grouped_stop_usages = {}
    for stop_usage in stop_usages:
        key = (stop_usage.line_name, stop_usage.inbound)
        if key not in grouped_stop_usages:
            grouped_keys.append(key)
            grouped_stop_usages[key] = []
        grouped_stop_usages[key].append(stop_usage)

    for line_name, inbound in grouped_keys:
        for from_usage, to_usage in pairwise(grouped_stop_usages[(line_name, inbound)]):
            pair = (from_usage.stop_id, to_usage.stop_id)
            if pair in seen_pairs or from_usage.stop_id == to_usage.stop_id:
                continue
            seen_pairs.add(pair)

            route_link = route_links.get(pair)
            if route_link:
                coordinates = list(route_link.geometry.coords)
                # Get waypoints for this segment
                waypoints = [
                    {
                        "id": waypoint.id,
                        "latitude": waypoint.latitude,
                        "longitude": waypoint.longitude,
                        "order": waypoint.order,
                    }
                    for waypoint in route_link.waypoints.all().order_by("order")
                ]
            else:
                coordinates = [
                    from_usage.stop.latlong.coords,
                    to_usage.stop.latlong.coords,
                ]
                waypoints = []

            segments.append(
                {
                    "id": f"{from_usage.stop_id}:{to_usage.stop_id}",
                    "line_name": line_name,
                    "inbound": inbound,
                    "from_stop_id": from_usage.stop_id,
                    "to_stop_id": to_usage.stop_id,
                    "from_stop_name": _route_editor_stop_name(from_usage.stop),
                    "to_stop_name": _route_editor_stop_name(to_usage.stop),
                    "from_stop_coordinates": list(from_usage.stop.latlong.coords),
                    "to_stop_coordinates": list(to_usage.stop.latlong.coords),
                    "coordinates": [list(coord) for coord in coordinates],
                    "has_route_link": route_link is not None,
                    "override": route_link.override if route_link else False,
                    "waypoints": waypoints,
                }
            )

    return segments


def _route_editor_stops_geojson(service):
    stops = {}
    for stop_usage in (
        service.stopusage_set.select_related("stop", "stop__locality")
        .filter(stop__latlong__isnull=False)
        .order_by("order", "id")
    ):
        stop = stop_usage.stop
        if stop.atco_code in stops:
            continue
        stops[stop.atco_code] = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": list(stop.latlong.coords),
            },
            "properties": {
                "atco_code": stop.atco_code,
                "name": stop.get_qualified_name(),
                "bearing": stop.get_heading(),
                "url": stop.get_absolute_url(),
                "services": stop.line_names if hasattr(stop, "line_names") else [],
            },
        }
    return {
        "type": "FeatureCollection",
        "features": list(stops.values()),
    }


@login_required
def route_editor(request):
    _require_route_editor_staff(request)

    selected_service = None
    service_id = request.GET.get("service")
    if service_id and service_id.isdigit():
        selected_service = _route_editor_service_queryset().filter(id=service_id).first()

    return render(
        request,
        "route_editor.html",
        {
            "object": selected_service,
            "selected_service": selected_service,
            "selected_service_id": selected_service.id if selected_service else None,
            "ad": False,
        },
    )


@login_required
def route_editor_search(request):
    _require_route_editor_staff(request)

    query = (request.GET.get("q") or "").strip()
    results = []
    if query:
        services = (
            _route_editor_service_queryset()
            .filter(
                Q(line_name__icontains=query)
                | Q(description__icontains=query)
                | Q(service_code__icontains=query)
                | Q(line_brand__icontains=query)
                | Q(operator__name__icontains=query)
            )
            .distinct()
            .order_by("line_name", "description")[:15]
        )
        for service in services:
            results.append(
                {
                    "id": service.id,
                    "line_name": service.get_line_name(),
                    "description": service.description,
                    "service_code": service.service_code,
                    "slug": service.slug,
                    "url": service.get_absolute_url(),
                    "operators": [operator.name for operator in service.operator.all()],
                }
            )

    return JsonResponse({"results": results})


@login_required
def route_editor_service_data(request, service_id):
    _require_route_editor_staff(request)

    service = get_object_or_404(_route_editor_service_queryset(), id=service_id)
    segments = _route_editor_segments(service)
    stop_ids = {
        segment["from_stop_id"] for segment in segments
    } | {segment["to_stop_id"] for segment in segments}
    stops = (
        service.stops.filter(atco_code__in=stop_ids, latlong__isnull=False)
        .annotate(line_names=stop_line_names)
        .distinct()
        .order_by()
        .select_related("locality")
    )

    stops_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": list(stop.latlong.coords),
                },
                "properties": {
                    "atco_code": stop.atco_code,
                    "naptan_code": stop.naptan_code,
                    "name": stop.get_qualified_name(),
                    "bearing": stop.get_heading(),
                    "url": stop.get_absolute_url(),
                    "services": stop.line_names,
                },
            }
            for stop in stops
        ],
    }

    return JsonResponse(
        {
            "service": {
                "id": service.id,
                "line_name": service.get_line_name(),
                "description": service.description,
                "service_code": service.service_code,
                "slug": service.slug,
                "url": service.get_absolute_url(),
                "operators": [operator.name for operator in service.operator.all()],
            },
            "stops": stops_geojson,
            "segments": segments,
        }
    )


@login_required
@require_http_methods(["POST"])
def route_editor_save(request, service_id):
    _require_route_editor_staff(request)

    service = get_object_or_404(Service, id=service_id, current=True)

    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON payload.")

    segments = payload.get("segments")
    if not isinstance(segments, list):
        return HttpResponseBadRequest("Expected a segments array.")

    existing_links = {
        (route_link.from_stop_id, route_link.to_stop_id): route_link
        for route_link in service.routelink_set.all()
    }
    touched_pairs = set()
    updated = 0
    created = 0
    deleted = 0
    waypoints_updated = 0
    waypoints_created = 0
    waypoints_deleted = 0

    with transaction.atomic():
        for segment in segments:
            if not isinstance(segment, dict):
                return HttpResponseBadRequest("Each segment must be an object.")

            from_stop_id = segment.get("from_stop_id")
            to_stop_id = segment.get("to_stop_id")
            coordinates = segment.get("coordinates") or []
            waypoints_data = segment.get("waypoints") or []

            if not from_stop_id or not to_stop_id:
                return HttpResponseBadRequest("Each segment must include from_stop_id and to_stop_id.")

            pair = (from_stop_id, to_stop_id)
            touched_pairs.add(pair)

            if coordinates:
                if len(coordinates) < 2:
                    return HttpResponseBadRequest("A saved segment needs at least two coordinates.")

                cleaned_coordinates = []
                for point in coordinates:
                    if not isinstance(point, (list, tuple)) or len(point) != 2:
                        return HttpResponseBadRequest("Each coordinate must be a [lng, lat] pair.")
                    lng = float(point[0])
                    lat = float(point[1])
                    cleaned_coordinates.append((lng, lat))

                geometry = LineString(cleaned_coordinates, srid=4326)
                route_link = existing_links.get(pair)
                if route_link:
                    route_link.geometry = geometry
                    route_link.override = True
                    route_link.save(update_fields=["geometry", "override"])
                    updated += 1
                else:
                    route_link = RouteLink.objects.create(
                        service=service,
                        from_stop_id=from_stop_id,
                        to_stop_id=to_stop_id,
                        geometry=geometry,
                        override=True,
                    )
                    created += 1

                # Handle waypoints for this segment
                existing_waypoints = {
                    wp.id: wp for wp in route_link.waypoints.all()
                }
                seen_waypoint_ids = set()

                for wp_data in waypoints_data:
                    if not isinstance(wp_data, dict):
                        return HttpResponseBadRequest("Each waypoint must be an object.")

                    wp_id = wp_data.get("id")
                    latitude = wp_data.get("latitude")
                    longitude = wp_data.get("longitude")
                    order = wp_data.get("order")

                    if latitude is None or longitude is None or order is None:
                        return HttpResponseBadRequest("Each waypoint must include latitude, longitude, and order.")

                    if wp_id and wp_id in existing_waypoints:
                        # Update existing waypoint
                        waypoint = existing_waypoints[wp_id]
                        waypoint.latitude = float(latitude)
                        waypoint.longitude = float(longitude)
                        waypoint.order = int(order)
                        waypoint.save(update_fields=["latitude", "longitude", "order"])
                        seen_waypoint_ids.add(wp_id)
                        waypoints_updated += 1
                    else:
                        # Create new waypoint
                        RouteWaypoint.objects.create(
                            route_link=route_link,
                            latitude=float(latitude),
                            longitude=float(longitude),
                            order=int(order),
                        )
                        waypoints_created += 1

                # Delete waypoints not in the payload
                for wp_id, waypoint in existing_waypoints.items():
                    if wp_id not in seen_waypoint_ids:
                        waypoint.delete()
                        waypoints_deleted += 1

            else:
                route_link = existing_links.get(pair)
                if route_link:
                    # Delete associated waypoints
                    route_link.waypoints.all().delete()
                    waypoints_deleted += route_link.waypoints.count()
                    route_link.delete()
                    deleted += 1

    service.save(update_fields=["modified_at"])

    return JsonResponse(
        {
            "ok": True,
            "updated": updated,
            "created": created,
            "deleted": deleted,
            "touched_pairs": len(touched_pairs),
            "waypoints_updated": waypoints_updated,
            "waypoints_created": waypoints_created,
            "waypoints_deleted": waypoints_deleted,
        }
    )


SITE_MAP_PERMISSION_BY_PATH = {
    "/admin/": "superuser",
    "/staff/stats": "staff",
    "/services/route-editor": "staff",
    "/services/route-editor/search": "staff",
    "/services/<int:service_id>/route-editor.json": "staff",
    "/services/<int:service_id>/route-editor/save": "staff",
    "/stops/<atco_code>/debug": "staff",
    "/trips/<int:trip_id>/snap": "staff",
    "/journeys/<int:journey_id>/snap": "staff",
}


def _normalise_site_map_path(path):
    path = path.replace("//", "/")
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def _site_map_entries(patterns, prefix=""):
    entries = []
    for pattern in patterns:
        if isinstance(pattern, URLPattern):
            route = str(pattern.pattern)
            if route.startswith("^"):
                continue
            full_path = _normalise_site_map_path(f"{prefix}{route}")
            entries.append(
                {
                    "path": full_path.rstrip("/") or "/",
                    "name": pattern.name or "",
                }
            )
        elif isinstance(pattern, URLResolver):
            route = str(pattern.pattern)
            if route.startswith("^"):
                continue
            entries.extend(_site_map_entries(pattern.url_patterns, f"{prefix}{route}"))
    return entries


def _site_map_section(path):
    if path == "/":
        return "Root"
    first = path.strip("/").split("/", 1)[0]
    return first.replace("-", " ").title()


def _site_map_permission(path):
    return SITE_MAP_PERMISSION_BY_PATH.get(path, "")


def site_map(request):
    entries = []
    seen = set()

    for entry in _site_map_entries(get_resolver().url_patterns):
        path = entry["path"]
        if path in seen:
            continue
        seen.add(path)
        entries.append(
            {
                "path": path,
                "name": entry["name"],
                "section": _site_map_section(path),
                "permission": _site_map_permission(path),
            }
        )

    entries.sort(key=lambda entry: (entry["section"], entry["path"]))

    sections = []
    current_section = None
    current_entries = []
    for entry in entries:
        if entry["section"] != current_section:
            if current_entries:
                sections.append({"title": current_section, "entries": current_entries})
            current_section = entry["section"]
            current_entries = [entry]
        else:
            current_entries.append(entry)
    if current_entries:
        sections.append({"title": current_section, "entries": current_entries})

    return render(
        request,
        "site_map.html",
        {
            "sections": sections,
            "ad": False,
        },
    )


class OperatorSitemap(Sitemap):
    protocol = "https"

    def items(self):
        return (
            Operator.objects.filter(
                ceased_operations_on__isnull=True
            ).filter(
                Exists(
                    Vehicle.objects.filter(
                        operator=OuterRef('pk'),
                        **current_vehicle_filters(
                            withdrawn=False,
                            preserved=False,
                        )
                    )
                )
            )
            .annotate(
                lastmod=Coalesce(
                    SubqueryMax("vehicle__manual_updated_at"),
                    "modified_at",
                )
            )
            .only("slug")
            .order_by("noc")
        )

    def lastmod(self, obj):
        return obj.lastmod


class VehicleSitemap(Sitemap):
    protocol = "https"

    def items(self):
        return (
            apply_vehicle_schema_compat(
                Vehicle.objects.filter(
                    **current_vehicle_filters(
                        withdrawn=False,
                        preserved=False,
                        operator__isnull=False,
                    )
                )
            )
            .only("slug", "id")
            .order_by("id")
        )


class ServiceSitemap(Sitemap):
    protocol = "https"

    def items(self):
        return Service.objects.filter(current=True).only("slug", "modified_at")

    def lastmod(self, obj):
        return obj.modified_at


@cdn_cache_control(max_age=300)
def search(request):
    form = forms.SearchForm(request.GET)

    context = {
        "form": form,
    }

    if form.is_valid():
        query_text = form.cleaned_data["q"].strip()
        context["query"] = query_text

        if query_text:
            query = SearchQuery(query_text, search_type="websearch", config="english")
            rank = SearchRank(F("search_vector"), query)
            compact = query_text.replace(" ", "")

            operators = Operator.objects.annotate(
                has_current_vehicles=Exists(
                    "vehicle",
                    filter=Q(
                        **current_vehicle_filters(
                            withdrawn=False,
                            preserved=False,
                        )
                    ),
                )
            )
            operators = operators.filter(
                Q(noc__iexact=compact)
                | Q(search_vector=query)
            ).annotate(
                exact_noc_match=Case(
                    When(noc__iexact=compact, then=Value(1)),
                    default=Value(0),
                ),
                rank=rank,
                headline=SearchHeadline("name", query, config="english"),
            )
            context["operators"] = Paginator(
                operators.order_by("-exact_noc_match", "-rank", "noc"), 20
            ).get_page(request.GET.get("page"))

            context["vehicles"] = (
                apply_vehicle_schema_compat(
                    Vehicle.objects.select_related("operator")
                    .filter(
                        Q(code__iexact=compact)
                        | Q(fleet_code__iexact=compact)
                        | Q(reg__iexact=compact)
                        | Q(name__icontains=query_text)
                        | Q(branding__icontains=query_text)
                    )
                )
                .filter(
                    **current_vehicle_filters(
                        withdrawn=False,
                        preserved=False,
                    )
                )
                .order_by("operator_id", "fleet_number", "fleet_code", "code")[:200]
            )
            user_filter = (
                Q(username__icontains=query_text)
                | Q(display_name__icontains=query_text)
                | Q(first_name__icontains=query_text)
                | Q(last_name__icontains=query_text)
            )
            if compact.isdigit():
                user_filter |= Q(id=int(compact))

            context["users"] = (
                User.objects.annotate(
                    review_count=Count("vehicle_reviews", distinct=True),
                    total_count=SubqueryCount("vehiclerevision"),
                )
                .filter(user_filter)
                .prefetch_related("manual_tags")
                .order_by("-trusted", "-total_count", "-review_count", "display_name", "username", "id")[:20]
            )
            context["preservation_groups"] = (
                PreservationGroup.objects.filter(
                    Q(name__icontains=query_text)
                    | Q(description__icontains=query_text)
                    | Q(slug__icontains=compact)
                )
                .annotate(vehicle_count=Count("preserved_vehicles"))
                .order_by("name")[:20]
            )

    return render(request, "search.html", context)


def journey(request):
    origin = request.GET.get("from")
    from_q = request.GET.get("from_q")
    destination = request.GET.get("to")
    to_q = request.GET.get("to_q")

    if origin:
        origin = get_object_or_404(Locality, slug=origin)
    if from_q:
        query = SearchQuery(from_q)
        rank = SearchRank(F("search_vector"), query)
        from_options = (
            Locality.objects.filter(search_vector=query)
            .annotate(rank=rank)
            .order_by("-rank")
        )
        if len(from_options) == 1:
            origin = from_options[0]
            from_options = None
        elif origin not in from_options:
            origin = None
    else:
        from_options = None

    if destination:
        destination = get_object_or_404(Locality, slug=destination)
    if to_q:
        query = SearchQuery(to_q)
        rank = SearchRank(F("search_vector"), query)
        to_options = (
            Locality.objects.filter(search_vector=query)
            .annotate(rank=rank)
            .order_by("-rank")
        )
        if len(to_options) == 1:
            destination = to_options[0]
            to_options = None
        elif destination not in to_options:
            destination = None
    else:
        to_options = None

    journeys = None
    # if origin and destination:
    #     journeys = Journey.objects.filter(
    #         stopusageusage__stop__locality=origin
    #     ).filter(stopusageusage__stop__locality=destination)
    # else:
    #     journeys = None

    return render(
        request,
        "journey.html",
        {
            "from": origin,
            "from_q": from_q or origin or "",
            "from_options": from_options,
            "to": destination,
            "to_q": to_q or destination or "",
            "to_options": to_options,
            "journeys": journeys,
        },
    )





@login_required
def ts_import(request):
    if not request.user.is_staff:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    if request.method == 'POST':
        ts_file = request.FILES.get('ts_import')
        if ts_file:
            import json
            from django.db.models import Q
            from fleet.completion import bulk_log_vehicles_for_user
            from vehicles.models import Vehicle
            try:
                ts_data = json.load(ts_file)
                if isinstance(ts_data, dict):
                    if 'data' in ts_data and isinstance(ts_data['data'], list):
                        items = ts_data['data']
                    else:
                        items = ts_data.values()
                else:
                    items = ts_data

                total_items = 0
                regs = []
                fleets = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    # Handle both the new format requested and fallback to the old format just in case
                    reg = item.get('bus_registration') or item.get('registration')
                    fleet = item.get('bus_fleet_number') or item.get('fleetnumber')
                    
                    if reg or fleet:
                        total_items += 1
                        if reg:
                            regs.append(reg)
                        if fleet:
                            fleets.append(str(fleet))
                
                created_logs_json = 0
                matched_count = 0
                
                if regs or fleets:
                    q_filter = Q()
                    if regs:
                        q_filter |= Q(reg__in=regs)
                    if fleets:
                        q_filter |= Q(fleet_number__in=[f for f in fleets if f.isdigit()])
                        q_filter |= Q(fleet_code__in=fleets)
                        q_filter |= Q(code__in=fleets)
                    
                    matching_vehicles = Vehicle.objects.filter(q_filter).distinct()
                    matched_count = matching_vehicles.count()
                    c, _ = bulk_log_vehicles_for_user(request.user, matching_vehicles)
                    created_logs_json = c
                
                errors = total_items - matched_count
                if errors < 0:
                    errors = 0
                    
                from django.contrib import messages
                messages.success(request, f'{created_logs_json} logged {errors} errors')
            except Exception as e:
                from django.contrib import messages
                messages.error(request, f'Error processing JSON: {e}')
        from django.shortcuts import redirect
        return redirect('ts_import')
        
    from django.shortcuts import render
    return render(request, 'ts_import.html', {
        'breadcrumb': [{'get_absolute_url': '/', '__str__': lambda: 'Home'}],
    })
