"Model definitions"

import datetime
import logging
import re
from urllib.parse import urlencode, urlparse

import yaml
from botocore.exceptions import NoCredentialsError
from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.gis.db.models import Extent
from django.contrib.gis.geos import Polygon
from django.contrib.postgres.aggregates import ArrayAgg
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Q, Value
from django.db.models.aggregates import StringAgg
from django.db.models.functions import Coalesce, Concat, Upper
from django.urls import reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from timezone_field import TimeZoneField

from bustimes.models import Route, TimetableDataSource, StopTime
from bustimes.timetables import Timetable
from bustimes.utils import get_descriptions
from .fields import AutoSlugField

TIMING_STATUS_CHOICES = (
    ("PPT", "Principal point"),
    ("TIP", "Time info point"),
    ("PTP", "Principal and time info point"),
    ("OTH", "Other bus stop"),
)
SERVICE_ORDER_REGEX = re.compile(r"(\D*)(\d*)(\D*)")
LOGO_FILE_EXTENSIONS = ("svg", "png", "jpg", "jpeg", "webp")
MAX_LOGO_FILE_SIZE_BYTES = 256 * 1024


def validate_logo_file_size(file_obj):
    if not file_obj:
        return
    size = getattr(file_obj, "size", None)
    if size is not None and size > MAX_LOGO_FILE_SIZE_BYTES:
        raise ValidationError(
            f"Logo files must be {MAX_LOGO_FILE_SIZE_BYTES // 1024} KB or smaller."
        )


logo_file_validators = [
    FileExtensionValidator(allowed_extensions=LOGO_FILE_EXTENSIONS),
    validate_logo_file_size,
]


def operator_slug_source(instance):
    return str(instance)


def service_slug_source(instance):
    """Generate a slug for a Service instance"""
    if instance.service_code:
        return instance.service_code
    if instance.line_name:
        return instance.line_name
    if instance.description:
        return instance.description
    # Fallback to string representation if nothing else is available
    return str(instance)


def validate_hex_colour(value):
    if value and not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value):
        raise ValidationError("Enter a three- or six-digit hexadecimal colour.")


class SearchMixin:
    def update_search_vector(self):
        instance = self._meta.default_manager.with_documents().get(pk=self.pk)
        instance.search_vector = instance.document
        instance.save(update_fields=["search_vector"])

    def save(self, *args, update_fields=None, **kwargs):
        super().save(*args, update_fields=update_fields, **kwargs)
        if update_fields is None or "search_vector" not in update_fields:
            self.update_search_vector()


class Region(models.Model):
    """The largest type of geographical area"""

    id = models.CharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=48)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def the(self):
        """Return the name for use in a sentence,
        with the definite article prepended if appropriate"""
        if self.name[-2:] in ("ds", "st"):
            return "the " + self.name
        else:
            return self.name

    def get_absolute_url(self):
        return reverse("region_detail", args=(self.id,))


class AdminArea(models.Model):
    """An administrative area within a region,
    or possibly a national transport (rail/air/ferry) network
    """

    id = models.PositiveSmallIntegerField(primary_key=True)
    atco_code = models.CharField(verbose_name="ATCO code", max_length=3)
    name = models.CharField(max_length=48)
    short_name = models.CharField(max_length=48, blank=True)
    country = models.CharField(max_length=3, blank=True)
    region = models.ForeignKey(Region, models.CASCADE)
    created_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("adminarea_detail", args=(self.id,))


class District(models.Model):
    """A district within an administrative area.
    Note: some administrative areas *do not* have districts.
    """

    id = models.PositiveSmallIntegerField(primary_key=True)
    name = models.CharField(max_length=48)
    admin_area = models.ForeignKey(AdminArea, models.CASCADE)
    created_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("district_detail", args=(self.id,))


class LocalityManager(models.Manager):
    def with_documents(self):
        vector = SearchVector("name", weight="A", config="english")
        vector += SearchVector("qualifier_name", weight="B", config="english")
        return self.get_queryset().annotate(document=vector)


class Locality(SearchMixin, models.Model):
    """A locality within an administrative area,
    and possibly within a district.

    Localities may be children of other localities...
    """

    id = models.CharField(max_length=48, primary_key=True)
    name = models.CharField(max_length=48)
    short_name = models.CharField(max_length=48, blank=True)
    qualifier_name = models.CharField(max_length=48, blank=True)
    slug = AutoSlugField(populate_from="get_qualified_name", editable=True, unique=True)
    admin_area = models.ForeignKey(AdminArea, models.CASCADE)
    district = models.ForeignKey(District, models.SET_NULL, null=True, blank=True)
    parent = models.ForeignKey("self", models.SET_NULL, null=True, blank=True)
    latlong = models.PointField(null=True, blank=True)
    adjacent = models.ManyToManyField("self", blank=True)
    search_vector = SearchVectorField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)

    objects = LocalityManager()

    class Meta:
        ordering = ("name",)
        indexes = [GinIndex(fields=["search_vector"])]

    def __str__(self):
        return self.name or self.id

    def get_qualified_name(self):
        """Return the name and qualifier (e.g. 'Reepham, Lincs')"""
        if self.qualifier_name:
            return f"{self.name}, {self.qualifier_name}"
        return str(self)

    def get_absolute_url(self):
        return reverse("locality_detail", args=(self.slug,))


class StopArea(models.Model):
    """A small area containing multiple stops, such as a bus station"""

    id = models.CharField(max_length=16, primary_key=True)
    name = models.CharField(max_length=48)
    admin_area = models.ForeignKey(AdminArea, models.CASCADE)

    TYPE_CHOICES = (
        ("GPBS", "on-street pair"),
        ("GCLS", "on-street cluster"),
        ("GAIR", "airport building"),
        ("GBCS", "bus/coach station"),
        ("GFTD", "ferry terminal/dock"),
        ("GTMU", "tram/metro station"),
        ("GRLS", "rail station"),
        ("GCCH", "coach service coverage"),
    )
    stop_area_type = models.CharField(max_length=4, choices=TYPE_CHOICES)

    parent = models.ForeignKey("self", models.SET_NULL, null=True, blank=True)
    latlong = models.PointField(null=True)
    active = models.BooleanField()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("stoparea_detail", args=(self.id,))


class StopGroup(models.Model):
    """A manually curated group of stops, such as a bus station."""

    name = models.CharField(max_length=100)
    slug = AutoSlugField(populate_from="name", editable=True, unique=True)
    location = models.PointField(null=True, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    stops = models.ManyToManyField("StopPoint", through="StopGroupStop", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("stopgroup_detail", args=(self.slug,))


class StopGroupStop(models.Model):
    group = models.ForeignKey(StopGroup, models.CASCADE)
    stop = models.ForeignKey("StopPoint", models.CASCADE)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("order", "stop__common_name", "stop__indicator")
        unique_together = ("group", "stop")

    def __str__(self):
        return f"{self.group}: {self.stop}"


class DataSource(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    description = models.CharField(blank=True)
    url = models.URLField(blank=True, db_index=True)
    datetime = models.DateTimeField(null=True, blank=True)
    sha1 = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    settings = models.JSONField(null=True, blank=True)
    source = models.ForeignKey(
        TimetableDataSource, models.CASCADE, null=True, blank=True
    )
    # for HTTP "if-modified-since" and "if-none-match":
    last_modified = models.DateTimeField(null=True, blank=True)
    etag = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return "/data"

    def get_nice_name(self):
        return self.name.split("_")[0]

    def get_nice_url(self):
        if not self.url:
            return

        parsed_url = urlparse(self.url)

        # BODS
        if parsed_url.hostname and parsed_url.hostname.endswith(".bus-data.dft.gov.uk"):
            return self.url.replace("download/", "")
        # Passenger
        if (
            parsed_url.path == "/open-data"
            or parsed_url.hostname == "data.discoverpassenger.com"
        ):
            return self.url
        if parsed_url.hostname:
            match parsed_url.hostname:
                case "opendata.stagecoachbus.com":
                    return "https://www.stagecoachbus.com/open-data"
                case "www.transportforireland.ie":
                    return f"https://www.transportforireland.ie/transitData/PT_Data.html#:~:text={self.name}"

    def is_tnds(self):
        match self.name:
            case (
                "L"
                | "GB"
                | "Y"
                | "SW"
                | "SE"
                | "EM"
                | "EA"
                | "WM"
                | "S"
                | "NE"
                | "NW"
                | "W"
                | "IM"
            ):
                return True
        return False

    def credit(self, route=None):
        url = self.get_nice_url()
        text = None
        date = self.datetime

        if self.is_tnds():
            match self.name:
                case "L":
                    text = "Transport for London"
                case "GB":
                    url = "https://data.bus-data.dft.gov.uk/coach/download"
                    text = "the Bus Open Data Service (BODS)"
                case _:
                    url = "https://www.travelinedata.org.uk/"
                    text = "the Traveline National Dataset (TNDS)"
        elif url:
            text = self.get_nice_name()
            hostname = urlparse(url).hostname
            if hostname.endswith(".bus-data.dft.gov.uk"):
                text = f"{text}/Bus Open Data Service (BODS)"
            elif hostname == "www.transportforireland.ie":
                text = "National Transport Authority"
        elif urlparse(self.url).hostname == "opendata.ticketer.com":
            text = self.url
        elif self.name == "MET" or self.name == "ULB":
            url = self.url
            text = "Translink open data"
        else:
            text = self.name

        if text == "FlixBus":
            url = "https://transport.data.gouv.fr/datasets/flixbus-horaires-theoriques-du-reseau-europeen-1"
        elif text == "TfGM":
            url = "https://www.data.gov.uk/dataset/c3ca6469-7955-4a57-8bfc-58ef2361b797/gm-public-transport-schedules-gtfs"

        if route:
            # get date from 'bluestar_1611829131.zip/Bluestar 31 01 2021_SER2.xml'
            timestamp = route.code.split("/")[0].split("_")[-1].removesuffix(".zip")
            if timestamp.isdigit():
                timestamp = int(timestamp)
                if timestamp > 1600000000:
                    date = datetime.datetime.fromtimestamp(int(timestamp))

        if text:
            if url:
                text = format_html('<a href="{}" rel="nofollow">{}</a>', url, text)
            else:
                text = escape(text)
            if date:
                text = mark_safe(
                    f"""{text}, <time datetime="{date.date()}">{date:%-d %B %Y}</time>"""
                )
            return text

        return ""

    def older_than(self, when):
        if not self.datetime or not when or self.datetime < when:
            return True
        return False

    def get_s3_path(self):
        return f"source/{self.id}/{self.datetime.isoformat()}"

    def upload_to_s3_etc(self, path):
        import boto3

        client = boto3.client("s3", endpoint_url="https://ams3.digitaloceanspaces.com")
        try:
            client.upload_file(path, "bustimes-data", self.get_s3_path())
        except NoCredentialsError:
            pass


class BustimesSyncState(models.Model):
    """Last applied Bustimes API state for field-level sync protection."""

    object_type = models.CharField(max_length=50)
    external_id = models.CharField(max_length=100)
    local_model = models.CharField(max_length=100, blank=True)
    local_pk = models.CharField(max_length=100, blank=True)
    last_fields = models.JSONField(default=dict, blank=True)
    last_payload = models.JSONField(default=dict, blank=True)
    protected_fields = models.JSONField(default=list, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("object_type", "external_id")
        indexes = [
            models.Index(fields=("object_type", "external_id")),
            models.Index(fields=("local_model", "local_pk")),
        ]

    def __str__(self):
        return f"{self.object_type} {self.external_id}"


class DataChangeLog(models.Model):
    """Audit and approval queue for command/import driven data changes."""

    STATUS_PENDING = "pending"
    STATUS_APPLIED = "applied"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending approval"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_REJECTED, "Rejected"),
    )

    source = models.CharField(max_length=120, db_index=True)
    target_model = models.CharField(max_length=100, db_index=True)
    target_pk = models.CharField(max_length=100, blank=True, db_index=True)
    target_repr = models.CharField(max_length=255, blank=True)
    operation = models.CharField(max_length=20, default="update", db_index=True)
    changes = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_data_change_logs",
    )

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("status", "target_model")),
            models.Index(fields=("source", "created_at")),
        ]

    def __str__(self):
        return f"{self.source}: {self.target_model} {self.target_pk or '(new)'}"


class StopFeature(models.Model):
    class Category(models.TextChoices):
        FEATURE = "feature", "Feature"
        ACCESSIBILITY = "accessibility", "Accessibility"

    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.FEATURE,
    )

    class Meta:
        ordering = ("category", "name")

    def __str__(self):
        return self.name


class StopPoint(models.Model):
    """The smallest type of geographical point.
    A point at which vehicles stop"""

    source = models.ForeignKey(DataSource, models.DO_NOTHING, null=True, blank=True)

    atco_code = models.CharField(
        verbose_name="ATCO code", max_length=36, primary_key=True
    )
    naptan_code = models.CharField(
        verbose_name="NaPTAN code", max_length=16, null=True, blank=True
    )
    crs_code = models.CharField(
        verbose_name="CRS code", max_length=3, null=True, blank=True, db_index=True
    )

    common_name = models.CharField(max_length=48)
    short_common_name = models.CharField(max_length=48, blank=True)
    landmark = models.CharField(max_length=48, blank=True)
    street = models.CharField(max_length=48, blank=True)
    crossing = models.CharField(max_length=48, blank=True)
    indicator = models.CharField(max_length=48, blank=True)

    latlong = models.PointField(null=True, blank=True)

    parents = models.ManyToManyField("self", blank=True)
    stop_area = models.ForeignKey(StopArea, models.SET_NULL, null=True, blank=True)
    locality = models.ForeignKey("Locality", models.SET_NULL, null=True, blank=True)
    suburb = models.CharField(max_length=48, blank=True)
    town = models.CharField(max_length=48, blank=True)
    locality_centre = models.BooleanField(null=True)

    heading = models.PositiveIntegerField(null=True, blank=True)

    timezone = TimeZoneField(null=True, blank=True)

    description = models.CharField(null=True, blank=True)
    notes = models.CharField(null=True, blank=True)
    features = models.ManyToManyField(StopFeature, blank=True)

    BEARING_CHOICES = (
        ("N", "north \u2191"),
        ("NE", "north-east \u2197"),
        ("E", "east \u2192"),
        ("SE", "south-east \u2198"),
        ("S", "south \u2193"),
        ("SW", "south-west \u2199"),
        ("W", "west \u2190"),
        ("NW", "north-west \u2196"),
    )
    bearing = models.CharField(max_length=2, choices=BEARING_CHOICES, blank=True)

    STOP_TYPE_CHOICES = (
        ("AIR", "Airport entrance"),
        ("GAT", "Air airside area"),
        ("FTD", "Ferry terminal/dock entrance"),
        ("FER", "Ferry/dock berth area"),
        ("FBT", "Ferry berth"),
        ("RSE", "Rail station entrance"),
        ("RLY", "Rail platform access area"),
        ("RPL", "Rail platform"),
        ("TMU", "Tram/metro/underground entrance"),
        ("MET", "Tram/metro/underground access area"),
        ("PLT", "Metro and underground platform access area"),
        ("BCE", "Bus/coach station entrance"),
        ("BCS", "Bus/coach bay/stand/stance within bus/coach station"),
        ("BCQ", "Bus/coach bay"),
        ("BCT", "On street bus/coach/tram stop"),
        ("TXR", "Taxi rank (head of)"),
        ("STR", "Shared taxi rank (head of)"),
    )
    stop_type = models.CharField(max_length=3, choices=STOP_TYPE_CHOICES, blank=True)

    BUS_STOP_TYPE_CHOICES = (
        ("MKD", "Marked (pole, shelter etc)"),
        ("HAR", "Hail and ride"),
        ("CUS", "Custom (unmarked, or only marked on road)"),
        ("FLX", "Flexible zone"),
    )
    bus_stop_type = models.CharField(
        max_length=3, choices=BUS_STOP_TYPE_CHOICES, blank=True
    )

    timing_status = models.CharField(
        max_length=3, choices=TIMING_STATUS_CHOICES, blank=True
    )

    admin_area = models.ForeignKey("AdminArea", models.SET_NULL, null=True, blank=True)
    active = models.BooleanField(db_index=True)

    created_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    revision_number = models.PositiveSmallIntegerField(null=True, blank=True)
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        ordering = ("common_name", "atco_code")
        indexes = [
            models.Index(Upper("naptan_code"), name="naptan_code"),
        ]
        constraints = [
            models.UniqueConstraint(Upper("atco_code"), name="atco_code"),
        ]

    def __str__(self):
        name = self.get_unqualified_name()
        if self.bearing:
            name = f"{name} {self.get_arrow()}"
        return name

    def get_heading(self):
        """Return the stop's bearing converted to degrees, for use with Google Street View."""
        if self.heading:
            return self.heading
        headings = {
            "N": 0,
            "NE": 45,
            "E": 90,
            "SE": 135,
            "S": 180,
            "SW": 225,
            "W": 270,
            "NW": 315,
        }
        return headings.get(self.bearing)

    prepositions = {
        "opp": "opposite",
        "adj": "adjacent to",
        "at": "at",
        "o/s": "outside",
        "nr": "near",
        "before": "before",
        "after": "after",
        "by": "by",
        "on": "on",
        "in": "in",
        "opposite": "opposite",
        "outside": "outside",
    }

    def get_unqualified_name(self):
        if self.indicator:
            if (
                " " in self.indicator
                and self.indicator.lower() in self.common_name.lower()
            ):
                return self.common_name  # not 'Bus Station stand V (Stand V)'
            return f"{self.common_name} ({self.indicator})"
        if self.atco_code[:3] == "940":
            return self.common_name.replace(" Underground Station", "")
        return self.common_name

    def get_arrow(self):
        if self.bearing:
            return self.get_bearing_display().split()[-1]
        return ""

    def get_qualified_name(self, short=True):
        if display_name := getattr(self, "_timetable_display_name", ""):
            return display_name
        name = self.get_unqualified_name()
        if self.locality:
            locality_name = self.locality.name.replace(" Town Centre", "").replace(
                " City Centre", ""
            )
            if self.common_name and locality_name.endswith(self.common_name):
                return locality_name.replace(self.common_name, name)  # Cardiff Airport
            if slugify(locality_name).split("-", 1)[0] not in slugify(self.common_name):
                if self.indicator.lower() in self.prepositions:
                    indicator = self.indicator.lower()
                    if not short:
                        indicator = self.prepositions[indicator]
                    return f"{locality_name}, {indicator} {self.common_name}"
                return f"{locality_name} {name}"
        elif self.town not in self.common_name:
            return f"{self.town} {name}"
        return name

    def get_name_for_timetable(self):
        if self.locality:
            locality_name = self.locality.name.replace(" Town Centre", "").replace(
                " City Centre", ""
            )
            if locality_name not in self.common_name:
                return f"{locality_name} {self.common_name}"
        return self.common_name

    def get_long_name(self):
        return self.get_qualified_name(short=False)

    def get_region(self):
        if self.admin_area_id:
            return self.admin_area.region
        return Region.objects.filter(service__stops=self).first()

    def get_absolute_url(self):
        return reverse("stoppoint_detail", args=(self.atco_code,))

    def get_edit_url(self):
        return reverse("stoppoint_edit", args=(self.atco_code,))

    def get_features_by_category(self, category):
        return [feature for feature in self.features.all() if feature.category == category]

    def get_standard_features(self):
        return self.get_features_by_category(StopFeature.Category.FEATURE)

    def get_accessibility_features(self):
        return self.get_features_by_category(StopFeature.Category.ACCESSIBILITY)

    def get_icon(self):
        if self.indicator:
            if len(self.indicator) < 3 and not self.indicator.islower():
                return self.indicator

            parts = self.indicator.split()
            if len(parts) == 2 and len(parts[1]) < 3:
                a, b = parts
                match a.lower():
                    case "stop" | "bay" | "stand" | "stance" | "gate" | "platform":
                        return b

        if self.common_name:
            # "Bus Station A" or "Bus Station 4"
            parts = self.common_name.split()
            if (parts[-1].isdigit() or parts[-1].isupper()) and len(parts[-1]) < 3:
                return parts[-1]

    def get_line_names(self):
        return sorted(filter(None, self.line_names), key=Service.get_line_name_order)


class Organisation(models.Model):
    slug = models.SlugField(max_length=48, unique=True)
    name = models.CharField(max_length=100)
    legal_name = models.CharField(max_length=255, blank=True)
    short_name = models.CharField(max_length=100, blank=True)
    slogan = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    about = models.TextField(blank=True)
    logo = models.FileField(
        upload_to="organisations/logos",
        blank=True,
        null=True,
        validators=logo_file_validators,
        help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
    )
    banner = models.ImageField(
        upload_to="organisations/banners", blank=True, null=True
    )
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=100, blank=True)
    social_x = models.URLField(blank=True)
    social_fb = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_threads = models.URLField(blank=True)
    social_bluesky = models.URLField(blank=True)
    social_mastodon = models.URLField(blank=True)
    social_other = models.URLField(blank=True)
    header_background = models.CharField(max_length=20, blank=True)
    header_foreground = models.CharField(max_length=20, blank=True)
    accent_colour = models.CharField(max_length=20, blank=True)
    card_background = models.CharField(max_length=20, blank=True)
    button_background = models.CharField(max_length=20, blank=True)
    button_foreground = models.CharField(max_length=20, blank=True)
    custom_css = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("organisation_detail", args=(self.slug,))


class GovernmentAuthority(models.Model):
    slug = models.SlugField(max_length=48, unique=True)
    name = models.CharField(max_length=100)
    legal_name = models.CharField(max_length=255, blank=True)
    short_name = models.CharField(max_length=100, blank=True)
    slogan = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    about = models.TextField(blank=True)
    logo = models.FileField(
        upload_to="government-authorities/logos",
        blank=True,
        null=True,
        validators=logo_file_validators,
        help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
    )
    banner = models.ImageField(
        upload_to="government-authorities/banners", blank=True, null=True
    )
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=100, blank=True)
    social_x = models.URLField(blank=True)
    social_fb = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_threads = models.URLField(blank=True)
    social_bluesky = models.URLField(blank=True)
    social_mastodon = models.URLField(blank=True)
    social_other = models.URLField(blank=True)
    header_background = models.CharField(max_length=20, blank=True)
    header_foreground = models.CharField(max_length=20, blank=True)
    accent_colour = models.CharField(max_length=20, blank=True)
    card_background = models.CharField(max_length=20, blank=True)
    button_background = models.CharField(max_length=20, blank=True)
    button_foreground = models.CharField(max_length=20, blank=True)
    custom_css = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "government authority"
        verbose_name_plural = "government authorities"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("government_authority_detail", args=(self.slug,))

    def get_vehicles_url(self):
        return reverse("government_authority_vehicles", args=(self.slug,))

    def get_routes_url(self):
        return reverse("government_authority_routes", args=(self.slug,))

    def get_operators_url(self):
        return reverse("government_authority_operators", args=(self.slug,))



class PreservationGroup(models.Model):
    slug = models.SlugField(max_length=48, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    social_x = models.URLField(blank=True)
    social_fb = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_threads = models.URLField(blank=True)
    social_bluesky = models.URLField(blank=True)
    social_mastodon = models.URLField(blank=True)
    social_other = models.URLField(blank=True)
    founded_date = models.DateField(null=True, blank=True)
    logo = models.FileField(
        upload_to="preservation-groups/logos",
        blank=True,
        null=True,
        validators=logo_file_validators,
        help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
    )
    banner = models.ImageField(
        upload_to="preservation-groups/banners", blank=True, null=True
    )

    class Meta:
        app_label = "busstops"
        ordering = ("name",)
        verbose_name = "preservation group"
        verbose_name_plural = "preservation groups"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("preservation_group_detail", args=(self.slug,))


class Manufacturer(models.Model):
    slug = models.SlugField(max_length=48, unique=True)
    name = models.CharField(max_length=100)
    legal_name = models.CharField(max_length=255, blank=True)
    short_name = models.CharField(max_length=100, blank=True)
    slogan = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="manufacturers/logos", blank=True, null=True)
    banner = models.ImageField(
        upload_to="manufacturers/banners", blank=True, null=True
    )
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=100, blank=True)
    social_x = models.URLField(blank=True)
    social_fb = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_threads = models.URLField(blank=True)
    social_bluesky = models.URLField(blank=True)
    social_mastodon = models.URLField(blank=True)
    social_other = models.URLField(blank=True)
    header_background = models.CharField(max_length=20, blank=True)
    header_foreground = models.CharField(max_length=20, blank=True)
    accent_colour = models.CharField(max_length=20, blank=True)
    card_background = models.CharField(max_length=20, blank=True)
    button_background = models.CharField(max_length=20, blank=True)
    button_foreground = models.CharField(max_length=20, blank=True)
    custom_css = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Division"
        verbose_name_plural = "Divisions"
        verbose_name = "manufactor"
        verbose_name_plural = "manufactors"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("manufacturer_detail", args=(self.slug,))


class ManufacturerSite(models.Model):
    class SiteType(models.TextChoices):
        FACTORY = "factory", "factory"
        HEAD_OFFICE = "head-office", "head office"
        PROVING_GROUND = "proving-ground", "proving ground"
        ENGINEERING = "engineering", "engineering centre"
        SALES = "sales", "sales and support"
        OTHER = "other", "other"

    manufacturer = models.ForeignKey(
        Manufacturer, models.CASCADE, related_name="sites"
    )
    name = models.CharField(max_length=100)
    site_type = models.CharField(
        max_length=20, choices=SiteType.choices, default=SiteType.FACTORY
    )
    location = models.PointField(null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "manufactor site"
        verbose_name_plural = "manufactor sites"

    def __str__(self):
        return self.name


class Depot(models.Model):
    operator = models.ForeignKey("Operator", models.CASCADE)
    name = models.CharField(max_length=100)
    location = models.PointField()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class OperatorGroup(models.Model):
    slug = models.SlugField(max_length=48)
    name = models.CharField(max_length=100)
    organisation = models.ForeignKey(Organisation, models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True)
    logo = models.FileField(
        upload_to="operator-groups/logos",
        blank=True,
        null=True,
        validators=logo_file_validators,
        help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
    )
    banner = models.ImageField(
        upload_to="operator-groups/banners", blank=True, null=True
    )
    website = models.URLField(blank=True)
    social_x = models.URLField(blank=True)
    social_fb = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_threads = models.URLField(blank=True)
    social_bluesky = models.URLField(blank=True)
    social_mastodon = models.URLField(blank=True)
    social_other = models.URLField(blank=True)
    header_background = models.CharField(max_length=20, blank=True)
    header_foreground = models.CharField(max_length=20, blank=True)
    accent_colour = models.CharField(max_length=20, blank=True)
    custom_css = models.TextField(blank=True)
    group_fleet_numbering = models.BooleanField(default=True)
    allow_transfers = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("group_vehicles", args=(self.slug,))


class OperatorGroupDepot(models.Model):
    group = models.ForeignKey(OperatorGroup, models.CASCADE)
    name = models.CharField(max_length=100)
    location = models.PointField(null=True, blank=True)
    address = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class BlogTag(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = AutoSlugField(populate_from="name", editable=True, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("blog_tag_detail", args=(self.slug,))


class BlogPost(models.Model):
    title = models.CharField(max_length=160)
    slug = AutoSlugField(populate_from="title", editable=True, unique=True)
    excerpt = models.TextField(blank=True)
    body = models.TextField()
    tags = models.ManyToManyField(BlogTag, blank=True, related_name="posts")
    published = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-published_at", "-created_at")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("blog_post_detail", args=(self.slug,))

    def get_display_date(self):
        return self.published_at or self.created_at

    def get_reading_time_minutes(self):
        words = len((self.body or "").split())
        return max(1, round(words / 220))


class OperatorManager(models.Manager):
    def with_documents(self):
        vector = SearchVector("name", weight="A", config="english")
        vector += SearchVector("noc", weight="A", config="english")
        vector += SearchVector("aka", weight="B", config="english")
        return self.get_queryset().annotate(document=vector)


class Operator(SearchMixin, models.Model):
    """An entity that operates public transport services"""

    source = models.ForeignKey(DataSource, models.DO_NOTHING, null=True, blank=True)

    noc = models.CharField(max_length=10, primary_key=True)  # e.g. 'YCST'
    name = models.CharField(max_length=100, db_index=True)
    qualifier_name = models.CharField(max_length=100, blank=True)
    aka = models.CharField(max_length=100, blank=True)
    slogan = models.CharField(max_length=255, blank=True)
    logo = models.FileField(
        upload_to="operators",
        blank=True,
        null=True,
        validators=logo_file_validators,
        help_text="Upload an SVG, PNG, JPG, JPEG, or WebP logo up to 256 KB.",
    )
    slug = AutoSlugField(populate_from=operator_slug_source, editable=True, unique=True)
    vehicle_mode = models.CharField(max_length=48, blank=True)
    social_x = models.URLField(blank=True)
    social_fb = models.URLField(blank=True)
    social_instagram = models.URLField(blank=True)
    social_linkedin = models.URLField(blank=True)
    social_youtube = models.URLField(blank=True)
    social_tiktok = models.URLField(blank=True)
    social_threads = models.URLField(blank=True)
    social_bluesky = models.URLField(blank=True)
    social_mastodon = models.URLField(blank=True)
    social_other = models.URLField(blank=True)
    external_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    is_manual = models.BooleanField(default=False)
    manual_updated_at = models.DateTimeField(null=True, blank=True)
    preserved = models.BooleanField(
        default=False,
        help_text="Tick for discontinued/preserved fleets (e.g. historic brands).",
    )
    ceased_operations_on = models.DateField(
        null=True,
        blank=True,
        help_text="If preserved, the date this operator ceased operations.",
    )
    accurate_as_of = models.DateField(
        null=True,
        blank=True,
        help_text="The date this operator's fleet information is accurate as of.",
    )
    fleet_list_notes = models.TextField(
        blank=True,
        help_text=(
            "For preserved operators, optional replacement text for the note shown "
            "above the fleet list."
        ),
    )
    organisation = models.ForeignKey(Organisation, models.SET_NULL, null=True, blank=True)
    government_authority = models.ForeignKey(GovernmentAuthority, models.SET_NULL, null=True, blank=True)
    group = models.ForeignKey(OperatorGroup, models.SET_NULL, null=True, blank=True)
    siblings = models.ManyToManyField("self", blank=True)
    region = models.ForeignKey(Region, models.SET_NULL, null=True, blank=True)
    regions = models.ManyToManyField(Region, blank=True, related_name="operators")
    colour = models.ForeignKey("ServiceColour", models.SET_NULL, null=True, blank=True)
    header_background = models.CharField(max_length=20, blank=True)
    header_foreground = models.CharField(max_length=20, blank=True)
    accent_colour = models.CharField(max_length=20, blank=True)
    card_background = models.CharField(max_length=20, blank=True)
    button_background = models.CharField(max_length=20, blank=True)
    button_foreground = models.CharField(max_length=20, blank=True)
    custom_css = models.TextField(blank=True)

    address = models.CharField(max_length=128, blank=True)
    url = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=128, blank=True)
    twitter = models.CharField(max_length=255, blank=True)

    payment_methods = models.ManyToManyField("PaymentMethod", blank=True)
    check_dvla = models.BooleanField(
        default=False,
        help_text="If enabled, DVLA data will be checked every 72 hours for this operator's vehicles.",
    )
    dvla_last_checked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time DVLA data was checked for this operator's vehicles.",
    )
    user_role = models.CharField(
        max_length=16,
        blank=True,
        default="",
        choices=[
            ("owns", "owns"),
            ("runs", "runs"),
            ("manages", "manages"),
            ("represents", "represents"),
        ],
        help_text="How this user relates to the operator or group (shown on the public page).",
    )
    search_vector = SearchVectorField(null=True, blank=True)
    modified_at = models.DateTimeField(auto_now=True)

    objects = OperatorManager()

    class Meta:
        ordering = ("name",)
        indexes = [GinIndex(fields=["search_vector"])]

    def __repr__(self):
        return f"{self.noc}: {self.name}"

    def __str__(self):
        return self.get_public_name()

    def get_public_name(self) -> str:
        base = self.aka or self.name or self.noc
        if self.preserved:
            return f"{base} (preserved)"
        return str(base)

    def get_public_name_html(self):
        base = self.aka or self.name or self.noc
        if self.preserved:
            return format_html("{} <i>(preserved)</i>", base)
        return str(base)

    def get_vehicles_url(self):
        return reverse("operator_vehicles", args=(self.slug,))

    def get_detail_url(self):
        return reverse("operator_detail", args=(self.slug,))

    def get_routes_url(self):
        return reverse("operator_routes", args=(self.slug,))

    def get_absolute_url(self):
        return self.get_routes_url()

    def mode(self):
        return self.vehicle_mode

    def get_a_mode(self):
        """Return the the name of the operator's vehicle mode,
        with the correct indefinite article
        depending on whether it begins with a vowel.

        'Airline' becomes 'An airline', 'Bus' becomes 'A bus'.
        """
        mode = str(self.vehicle_mode).lower()
        if not mode or mode[0].lower() in "aeiou":
            return "An " + mode  # 'An airline' or 'An '
        return "A " + mode  # 'A hovercraft'


class OperatorVehicleColumn(models.Model):
    operator = models.ForeignKey(
        Operator, models.CASCADE, related_name="vehicle_columns"
    )
    name = models.CharField(max_length=80)
    slug = AutoSlugField(populate_from="name", editable=True)
    help_text = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("display_order", "name")
        constraints = [
            models.UniqueConstraint(
                Upper("name"),
                "operator",
                name="busstops_operator_vehicle_column_unique_name_per_operator",
            ),
            models.UniqueConstraint(
                "operator",
                "slug",
                name="busstops_operator_vehicle_column_unique_slug_per_operator",
            ),
        ]

    def __str__(self):
        return self.name

    def get_data_keys(self):
        return (self.slug, self.name)


class StopCode(models.Model):
    stop = models.ForeignKey(StopPoint, models.CASCADE)
    source = models.ForeignKey(
        "busstops.DataSource",
        models.CASCADE,
        limit_choices_to={
            "name__in": (
                "FlixBus",
                "National coach code",
            )
        },
        default=3695,  # FlixBus
    )
    code = models.CharField(max_length=100)

    class Meta:
        unique_together = ("code", "source")

    def __str__(self):
        return self.code


class OperatorCode(models.Model):
    operator = models.ForeignKey(Operator, models.CASCADE)
    source = models.ForeignKey(DataSource, models.CASCADE)
    code = models.CharField(max_length=100, db_index=True)

    class Meta:
        unique_together = ("operator", "code", "source")

    def __str__(self):
        return self.code


class StopUsage(models.Model):
    """A link between a StopPoint and a Service,
    with an order placing it in a direction (e.g. the first outbound stop)"""

    service = models.ForeignKey("Service", models.CASCADE)
    stop = models.ForeignKey(StopPoint, models.CASCADE)
    order = models.PositiveSmallIntegerField()
    timing_point = models.BooleanField(default=True)
    inbound = models.BooleanField(default=False)
    line_name = models.CharField()

    class Meta:
        ordering = ("inbound", "order")


class ServiceColour(models.Model):
    name = models.CharField(max_length=64, blank=True)
    foreground = models.CharField(max_length=20, blank=True)
    background = models.CharField(max_length=20, blank=True)
    border = models.CharField(max_length=20, blank=True)
    use_name_as_brand = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def preview(self, name=False):
        return format_html(
            '<div style="background:{};color:{}">{}</div>',
            self.background,
            self.foreground,
            self.name or "-",
        )


class ServiceManager(models.Manager):
    def with_documents(self):
        vector = SearchVector(
            StringAgg("route__line_name", Value(" "), distinct=True, default=""),
            weight="A",
            config="english",
        )
        vector += SearchVector("line_brand", weight="A", config="english")
        vector += SearchVector("description", weight="B", config="english")
        vector += SearchVector(
            StringAgg(
                Concat("operator__noc", Value(" "), "operator__name"),
                Value(" "),
                default="",
            ),
            weight="B",
            config="english",
        )
        vector += SearchVector(
            StringAgg(
                Concat("stops__locality__name", Value(" "), "stops__common_name"),
                Value(" "),
                default="",
            ),
            weight="C",
            config="english",
        )
        return self.get_queryset().annotate(document=vector)

    def with_line_names(self):
        return self.get_queryset().annotate(
            line_names=ArrayAgg(
                Coalesce("route__line_name", "line_name"), distinct=True, default=None
            )
        )


class Service(models.Model):
    """A bus service"""

    service_code = models.CharField(max_length=64, db_index=True, blank=True)
    line_name = models.CharField(max_length=64, blank=True)
    line_brand = models.CharField(max_length=64, blank=True)
    description = models.CharField(max_length=255, blank=True, db_index=True)
    slug = AutoSlugField(populate_from=service_slug_source, editable=True, unique=True)
    mode = models.CharField(max_length=11, blank=True, default="bus")
    operator = models.ManyToManyField(Operator, blank=True)
    region = models.ForeignKey(Region, models.CASCADE, null=True, blank=True)
    stops = models.ManyToManyField(StopPoint, through=StopUsage)
    current = models.BooleanField(default=True, db_index=True)
    non_current_route = models.BooleanField(default=False, db_index=True)
    event_specific = models.BooleanField(default=False, db_index=True)
    school_route = models.BooleanField(default=False, db_index=True)
    timetable_wrong = models.BooleanField(default=False)
    geometry = models.GeometryField(null=True, blank=True)

    source = models.ForeignKey(DataSource, models.SET_NULL, null=True, blank=True)
    tracking = models.BooleanField(default=False)
    payment_methods = models.ManyToManyField(
        "PaymentMethod", through="ServicePaymentMethod", blank=True
    )
    search_vector = SearchVectorField(null=True, blank=True)
    modified_at = models.DateTimeField(auto_now=True)

    public_use = models.BooleanField(null=True)

    colour = models.CharField(
        max_length=7,
        blank=True,
        validators=[validate_hex_colour],
        help_text="Hexadecimal colour, e.g. #1d4ed8.",
    )

    is_rail_replacement = models.BooleanField(
        default=False,
        db_index=True,
        help_text="This service is a rail replacement service.",
    )
    train_operator = models.CharField(
        max_length=255,
        blank=True,
        help_text="The train operator this service is covering for.",
    )

    objects = ServiceManager()
    update_search_vector = SearchMixin.update_search_vector

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(Upper("line_name"), name="line_name"),
            GinIndex(fields=["search_vector"]),
        ]

    def __str__(self):
        line_name = self.get_line_name()
        description = self.description
        if description == line_name:
            description = None
        elif (
            " " in line_name
            and line_name in description
            or line_name in self.line_brand
        ):
            line_name = None
        if line_name or self.line_brand or description:
            parts = (line_name, self.line_brand, description)
            return " - ".join(part for part in parts if part)
        return self.service_code

    def yaml(self):
        return yaml.dump(
            {
                self.service_code: {
                    "line_name": self.line_name,
                    "line_brand": self.line_brand,
                    "description": self.description,
                    "current": self.current,
                }
            }
        )

    def get_line_names(self):
        if hasattr(self, "line_names") and self.line_names:
            return self.line_names
        return [self.line_name]

    def get_line_name(self):
        return ", ".join(self.get_line_names())

    def get_line_name_and_brand(self):
        line_name = self.get_line_name()
        if self.line_brand:
            return f"{line_name} - {self.line_brand}"
        return line_name

    @property
    def colour_foreground(self):
        if not self.colour or not re.fullmatch(
            r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", self.colour
        ):
            return ""
        colour = self.colour.lstrip("#")
        if len(colour) == 3:
            colour = "".join(component * 2 for component in colour)
        red, green, blue = (
            int(colour[index : index + 2], 16) for index in range(0, 6, 2)
        )
        return "#fff" if 0.299 * red + 0.587 * green + 0.114 * blue <= 186 else "#000"

    def get_a_mode(self):
        if self.mode and self.mode[0].lower() in "aeiou":
            return f"An {self.mode}"  # 'An underground service'
        return f"A {self.mode}"  # 'A bus service' or 'A service'

    def get_absolute_url(self):
        return reverse("service_detail", args=(self.slug,))

    def get_order(self):
        if hasattr(self, "group"):
            return self.group, self.get_line_name_order(self.get_line_names()[0])
        return self.get_line_name_order(self.get_line_names()[0])

    @staticmethod
    def get_line_name_order(line_name):
        prefix, number, suffix = SERVICE_ORDER_REGEX.match(line_name).groups()
        number = number.zfill(4)
        if prefix == "X" or prefix == "N":
            return ("", number, prefix, suffix)
        return (prefix, number, suffix)

    def get_tfl_url(self) -> str:
        return f"https://tfl.gov.uk/bus/timetable/{self.line_name}/"

    def get_trapeze_link(self):
        domain = "travelinescotland.com"
        name = "Timetable on the Traveline Scotland website"
        query = (("serviceId", self.service_code.replace("_", " ")),)
        return f"https://www.{domain}/timetables?{urlencode(query)}", name

    def get_traveline_links(self, date=None) -> list:
        if not self.source_id:
            return []

        if (
            self.source.name == "S"
            and "_" in self.service_code
            and not self.service_code.startswith("S_")
        ):
            return [self.get_trapeze_link()]

        if self.source.name == "W" or self.region_id == "W":
            for service_code in self.servicecode_set.filter(scheme="Traveline Cymru"):
                query = (
                    ("routeNum", self.line_name),
                    ("direction_id", 0),
                    ("timetable_key", service_code.code),
                )
                url = "https://www.traveline.cymru/timetables/?" + urlencode(query)
                return [(url, "Timetable on the Traveline Cymru website")]

        elif (
            self.source.name == "L"
            and self.servicecode_set.filter(scheme="TfL").exists()
        ):
            return [
                (self.get_tfl_url(), "Timetable on the Transport for London website"),
            ]
        return []

    def get_similar_services(self):
        ids = self.link_from.values("to_service").union(
            self.link_to.values("from_service")
        )

    def get_timetable(self, day=None, calendar_id=None, also_services=None, line_names=None, detailed=False, day_of_week=None):
        from bustimes.timetables import Timetable
        from bustimes.models import Route

        routes = self.route_set.all()

        if also_services:
            for service in also_services:
                routes = routes.union(service.route_set.all())

        if line_names:
            routes = routes.filter(line_name__in=line_names)

        operators = self.operator.all()

        return Timetable(routes, date=day, calendar_id=calendar_id, detailed=detailed, operators=operators, day_of_week=day_of_week)

    def do_stop_usages(self):
        from bustimes.models import StopTime, Trip

        self.stopusage_set.all().delete()

        stop_times = (
            StopTime.objects.filter(trip__route__service=self)
            .select_related("trip__route", "stop")
            .order_by("trip__id", "id")
        )

        for trip in Trip.objects.filter(route__service=self).prefetch_related(
            "stoptime_set__stop"
        ):
            for i, stop_time in enumerate(trip.stoptime_set.all()):
                StopUsage.objects.get_or_create(
                    service=self,
                    stop=stop_time.stop,
                    defaults={
                        "order": i,
                        "timing_point": stop_time.pick_up or stop_time.set_down,
                        "inbound": trip.inbound,
                        "line_name": trip.route.line_name or self.line_name,
                    },
                )

    def update_geometry(self, save=True):
        from django.contrib.gis.geos import LineString, MultiLineString
        from bustimes.models import RouteLink

        route_links = self.routelink_set.filter(geometry__isnull=False).order_by(
            "id"
        )

        if not route_links.exists():
            self.geometry = None
        else:
            lines = [rl.geometry for rl in route_links]
            if len(lines) == 1:
                self.geometry = lines[0]
            else:
                self.geometry = MultiLineString(lines, srid=4326)

        if save:
            self.save(update_fields=["geometry"])

    def update_description(self):
        stops = (
            StopPoint.objects.filter(stopusage__service=self)
            .distinct()
            .order_by("stopusage__order")
        )

        if stops.count() >= 2:
            self.description = f"{stops.first().common_name} - {stops.last().common_name}"
            self.save(update_fields=["description"])


class RouteNotice(models.Model):
    service = models.ForeignKey(Service, models.CASCADE, related_name="route_notices")
    other_services = models.ManyToManyField(
        Service,
        blank=True,
        related_name="related_route_notices",
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    start = models.DateField()
    end = models.DateField()
    planned = models.BooleanField(default=False)
    diversion = models.BooleanField(default=False)
    diversion_num = models.PositiveSmallIntegerField(null=True, blank=True)
    route_map_id = models.CharField(max_length=80, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-start", "-end", "title")
        constraints = [
            models.CheckConstraint(
                condition=Q(diversion=False) | Q(diversion_num__isnull=False),
                name="route_notice_diversion_num_required",
            ),
            models.CheckConstraint(
                condition=Q(diversion_num__isnull=True) | Q(diversion_num__lte=9999),
                name="route_notice_diversion_num_0000_9999",
            ),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("route_notice_detail", args=(self.service.slug, self.pk))

    @property
    def route_map_base_id(self):
        operator = self.service.operator.order_by("noc").first()
        operator_code = operator.noc if operator else "UNKNOWN"
        line_order = self.service.get_line_name_order(self.service.get_line_name())
        return f"{line_order[1]}_{operator_code}"

    def build_route_map_id(self):
        base = self.route_map_base_id
        if self.diversion and self.diversion_num is not None:
            return f"{base}_{self.diversion_num:04d}"
        return base

    @property
    def diversion_num_display(self):
        if self.diversion_num is None:
            return ""
        return f"{self.diversion_num:04d}"

    def save(self, *args, **kwargs):
        self.route_map_id = self.build_route_map_id()
        super().save(*args, **kwargs)


class ServiceCode(models.Model):
    service = models.ForeignKey(Service, models.CASCADE)
    scheme = models.CharField(max_length=255)
    code = models.CharField(max_length=255)

    class Meta:
        unique_together = ("service", "scheme", "code")

    def __str__(self):
        return f"{self.scheme} {self.code}"


class ServiceLink(models.Model):
    from_service = models.ForeignKey(Service, models.CASCADE, "link_from")
    to_service = models.ForeignKey(Service, models.CASCADE, "link_to")
    how = models.CharField(
        max_length=10,
        choices=(
            ("parallel", "Combine timetables"),
            ("also", "Just list"),
        ),
    )

    def get_absolute_url(self):
        return self.from_service.get_absolute_url()



class HomepageNotice(models.Model):
    title = models.CharField(max_length=120, blank=True)
    message = models.TextField()
    from_date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-from_date", "-modified_at", "-id")

    def __str__(self):
        if self.title:
            return self.title
        return self.message[:60]
class PaymentMethod(models.Model):
    name = models.CharField(max_length=48)
    url = models.URLField(blank=True)

    def __str__(self):
        return self.name


class ServicePaymentMethod(models.Model):
    service = models.ForeignKey("Service", models.CASCADE)
    payment_method = models.ForeignKey("PaymentMethod", models.CASCADE)
    accepted = models.BooleanField(default=True)

    class Meta:
        unique_together = ("service", "payment_method")


class Contact(models.Model):
    from_name = models.CharField(max_length=255)
    from_email = models.EmailField()
    message = models.TextField()
    spam_score = models.PositiveIntegerField()
    ip_address = models.GenericIPAddressField()
    referrer = models.URLField(blank=True)


class SIRISource(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField()
    requestor_ref = models.CharField(max_length=255, blank=True)
    admin_areas = models.ManyToManyField(AdminArea, blank=True)
    operators = models.ManyToManyField(Operator, blank=True)

    def __str__(self):
        return self.name

    def get_poorly_key(self):
        return f"{self.url}:{self.requestor_ref}:poorly"

    def is_poorly(self):
        return cache.get(self.get_poorly_key())

