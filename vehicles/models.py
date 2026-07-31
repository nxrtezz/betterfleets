import datetime
from decimal import Decimal
import subprocess
import re
import struct
import uuid
from collections import Counter
from functools import lru_cache
from math import ceil
from urllib.parse import quote

from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.db import connection
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Upper
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, format_html
from simple_history.models import HistoricalRecords
from webcolors import HTML5SimpleColor, html5_parse_legacy_color

from busstops.fields import AutoSlugField
from busstops.models import DataSource, Operator, PreservationGroup, Service
from bustimes.utils import get_trip
from .fields import ColourField, ColoursField, CSSField


def validate_livery_image_file(file):
    if not file.name.lower().endswith(('.svg', '.png')):
        raise ValidationError('Only SVG and PNG files are allowed')


def format_reg(reg):
    if "-" not in reg:
        if reg[-3:].isalpha():
            return reg[:-3] + " " + reg[-3:]
        if reg[:3].isalpha():
            return reg[:3] + " " + reg[3:]
        if reg[-2:].isalpha():
            return reg[:-2] + " " + reg[-2:]
        if reg[:2].isalpha():
            return reg[:2] + " " + reg[2:]

    return reg


def get_css(colours, direction=None, horizontal=False, angle=None):
    if angle is None:
        angle = 90
    if len(colours) == 1:
        return colours[0]
    if direction is None:
        direction = 180
    else:
        direction = int(direction)
    background = "linear-gradient("
    if horizontal:
        background += "to top"
    elif direction < 180:
        background += f"{360 - angle}deg"
    else:
        background += f"{angle}deg"
    percentage = 100 / len(colours)
    for i, colour in enumerate(colours):
        if i != 0 and colour != colours[i - 1]:
            background += ",{} {}%".format(colour, ceil(percentage * i))
        if i != len(colours) - 1 and colour != colours[i + 1]:
            background += ",{} {}%".format(colour, ceil(percentage * (i + 1)))
    background += ")"

    return background


def get_brightness(colour: HTML5SimpleColor) -> float:
    """Returns a "relative luminance" between 0 and 255"""
    return 0.299 * colour.red + 0.587 * colour.green + 0.114 * colour.blue


def get_text_colour(colours) -> str:
    """Returns "#fff" if the colour is dark, otherwise None"""
    if not colours:
        return
    colours = colours.split()
    colours = [html5_parse_legacy_color(colour) for colour in colours]
    brightnesses = [get_brightness(colour) for colour in colours]
    colours_length = len(colours)
    if colours_length > 2:
        # ignore the leftmost and rightmost strips
        brightnesses = brightnesses[1:-1]
        colours_length -= 2
    if (sum(brightnesses) / colours_length) <= 186:
        return "#fff"


class VehicleTypeType(models.TextChoices):
    SINGLE_DECKER = "", "single decker"
    DOUBLE_DECKER = "double decker", "double decker"
    MINIBUS = "minibus", "minibus"
    COACH = "coach", "coach"
    DOUBLE_DECK_COACH = "decker coach", "double decker coach"
    ARTICULATED = "articulated", "bendy bus"
    TRAIN = "train", "train"
    TRAM = "tram", "tram"
    AMPHIBIOUS = "amphibious", "amphibious"


class FuelType(models.TextChoices):
    DIESEL = "diesel", "diesel"
    ELECTRIC = "electric", "electric"
    HYBRID = "hybrid", "hybrid"
    HYDROGEN = "hydrogen", "hydrogen"
    GAS = "gas", "gas"  # (compressed natural)


class DVLATaxStatus(models.TextChoices):
    NOT_TAXED_FOR_ON_ROAD_USE = "Not Taxed for on Road Use", "Not Taxed for on Road Use"
    SORN = "SORN", "SORN"
    TAXED = "Taxed", "Taxed"
    UNTAXED = "Untaxed", "Untaxed"


class DVLAMotStatus(models.TextChoices):
    NO_DETAILS_HELD_BY_DVLA = "No details held by DVLA", "No details held by DVLA"
    NO_RESULTS_RETURNED = "No results returned", "No results returned"
    NOT_VALID = "Not valid", "Not valid"
    VALID = "Valid", "Valid"


class VehicleTypeGroup(models.Model):
    manufacturer = models.ForeignKey(
        "busstops.Manufacturer",
        models.CASCADE,
        related_name="vehicle_type_groups",
        verbose_name="manufactor",
    )
    name = models.CharField(max_length=255)

    class Meta:
        app_label = "vehicles"
        ordering = ("manufacturer__name", "name")
        constraints = [
            UniqueConstraint(
                Upper("name"),
                "manufacturer",
                name="vehicles_vehicle_type_group_unique_name_per_manufacturer",
            )
        ]

    def __str__(self):
        return self.name


class VehicleType(models.Model):
    name = models.CharField(max_length=255, unique=True)
    style = models.CharField(choices=VehicleTypeType.choices, max_length=13, blank=True)
    fuel = models.CharField(choices=FuelType.choices, max_length=8, blank=True)
    company = models.CharField(max_length=255, blank=True)
    active_production = models.BooleanField(default=False)
    vehicle_group = models.ForeignKey(
        VehicleTypeGroup,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicle_types",
    )
    manufacturer = models.ForeignKey(
        "busstops.Manufacturer",
        models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="manufactor",
    )
    external_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    is_manual = models.BooleanField(default=False)
    manual_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "vehicles"
        ordering = ("name",)

    def __str__(self):
        return self.name

    @property
    def group_name(self):
        return self.vehicle_group.name if self.vehicle_group_id else self.name


class Livery(models.Model):
    class LiveryType(models.TextChoices):
        CSS = "css", "CSS"
        SVG = "svg", "SVG"

    name = models.CharField(max_length=255, db_index=True)
    livery_type = models.CharField(
        max_length=3,
        choices=LiveryType.choices,
        default=LiveryType.CSS,
        help_text="Type of livery: CSS gradients or SVG image"
    )
    svg = models.FileField(
        upload_to="liveries/svg",
        blank=True,
        null=True,
        validators=[validate_livery_image_file],
        help_text="SVG or PNG file with aspect ratio 3:2 (e.g., 90x60, 180x120)"
    )
    external_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    is_manual = models.BooleanField(default=False)
    manual_updated_at = models.DateTimeField(null=True, blank=True)
    show_name = models.BooleanField(default=True)
    colour = ColourField(
        max_length=7, help_text="For the most simplified version of the livery"
    )
    colours = ColoursField(
        max_length=512,
        blank=True,
        help_text="""Left and right CSS will be generated from this""",
    )
    angle = models.PositiveSmallIntegerField(null=True, blank=True)
    left_css = CSSField(
        max_length=1024,
        blank=True,
        verbose_name="Left CSS",
        help_text="Automatically generated from colours and angle",
    )
    right_css = CSSField(
        max_length=1024,
        blank=True,
        verbose_name="Right CSS",
        help_text="Should be a mirror image of the left CSS",
    )
    white_text = models.BooleanField(default=False)
    text_colour = ColourField(max_length=7, blank=True)
    stroke_colour = ColourField(
        max_length=7, blank=True, help_text="Use sparingly, often looks shit"
    )
    horizontal = models.BooleanField(
        default=False, help_text="Equivalent to setting the angle to 90"
    )
    joined_fleet = models.CharField(
        max_length=7,
        blank=True,
        help_text="MM-YYYY format (e.g., 01-2024)",
    )
    left_fleet = models.CharField(
        max_length=7,
        blank=True,
        help_text="MM-YYYY format (e.g., 12-2024)",
    )
    updated_at = models.DateTimeField(null=True, blank=True, auto_now=True)
    published = models.BooleanField(
        default=False,
        help_text="Tick to include in the CSS and be able to apply this livery to vehicles",
    )

    class Meta:
        app_label = "vehicles"
        ordering = ("name",)
        verbose_name_plural = "liveries"

    def __str__(self):
        return self.name


    @staticmethod
    def minify(css):
        prefix = ".livery{background:"
        suffix = "}"
        css = prefix + css + suffix
        completed_process = subprocess.run(
            ["lightningcss", "--minify"], input=css.encode(), capture_output=True
        )
        css = completed_process.stdout.decode().strip()
        assert css.startswith(prefix)
        assert css.endswith(suffix)
        return css[19:-1]

    def set_css(self):
        if self.colours:
            self.left_css = get_css(
                self.colours.split(), None, self.horizontal, self.angle
            )
            self.right_css = get_css(
                self.colours.split(), 90, self.horizontal, self.angle
            )

    def preview(self, name=False):
        if self.livery_type == self.LiveryType.SVG and self.svg:
            img = f'<img src="{self.svg.url}" style="height:1.5em;width:2.25em;object-fit:contain;" alt="{escape(self.name)}"'
            if name:
                return format_html(img + '>', self.name)
            else:
                return format_html(img + ' title="{}">', self.name)
        elif self.left_css:
            background = escape(self.left_css)
        elif self.colours:
            background = get_css(self.colours.split())
        elif name:
            background = ""
        else:
            return

        div = f'<div style="height:1.5em;width:2.25em;background:{background}"'
        if name:
            return format_html(div + "></div> {}", self.name)
        else:
            return format_html(div + ' title="{}"></div>', self.name)

    def clean(self):
        super().clean()
        if self.livery_type == self.LiveryType.SVG and self.svg:
            if self.svg.name.lower().endswith('.svg'):
                from xml.etree import ElementTree
                try:
                    tree = ElementTree.parse(self.svg)
                    root = tree.getroot()
                    width = root.get('width')
                    height = root.get('height')
                    
                    # Parse dimensions (handle units like px, or no units)
                    def parse_dimension(dim):
                        if not dim:
                            return None
                        dim = str(dim).lower().replace('px', '').strip()
                        try:
                            return float(dim)
                        except ValueError:
                            return None
                    
                    width_val = parse_dimension(width)
                    height_val = parse_dimension(height)
                    
                    if width_val and height_val:
                        ratio = width_val / height_val
                        # Target ratio is 2.25:1.5 = 1.5:1
                        if not (1.45 <= ratio <= 1.55):  # Allow small tolerance
                            raise ValidationError({
                                'svg': f'SVG aspect ratio must be approximately 3:2 (current: {width_val}:{height_val}, ratio: {ratio:.2f})'
                            })
                except ElementTree.ParseError:
                    raise ValidationError({'svg': 'Invalid SVG file'})
            elif self.svg.name.lower().endswith('.png'):
                from PIL import Image
                try:
                    img = Image.open(self.svg)
                    width, height = img.size
                    ratio = width / height
                    # Target ratio is 2.25:1.5 = 1.5:1
                    if not (1.45 <= ratio <= 1.55):  # Allow small tolerance
                        raise ValidationError({
                            'svg': f'PNG aspect ratio must be approximately 3:2 (current: {width}:{height}, ratio: {ratio:.2f})'
                        })
                except Exception:
                    raise ValidationError({'svg': 'Invalid PNG file'})

    def save(self, *args, update_fields=None, **kwargs):
        if update_fields is None:
            if self.livery_type == self.LiveryType.CSS:
                if self.colours:
                    self.set_css()
                    if self.colours and not self.id:
                        self.white_text = get_text_colour(self.colours) == "#fff"
                if self.right_css:
                    self.right_css = self.minify(self.right_css)
                    self.left_css = self.minify(self.left_css)
        super().save(*args, update_fields=update_fields, **kwargs)

    def get_styles(self, livery_ids=None):
        if not self.left_css:
            if self.colours:
                css = get_css(self.colours.split(), None, self.horizontal, self.angle)
                right_css = get_css(self.colours.split(), 90, self.horizontal, self.angle)
            else:
                return []
        else:
            css = self.left_css
            right_css = self.right_css
        if not livery_ids:
            livery_ids = (self.id,)
        selector = ",".join(f".livery-{livery_id}" for livery_id in livery_ids)
        css = f"  background: {css}"
        if self.text_colour:
            css = f"{css};\n  color: {self.text_colour}"
        elif self.white_text:
            css = f"{css};\n  color: #fff"
        if self.stroke_colour:
            css = f"{css};\n  stroke: {self.stroke_colour}"
        styles = [f"{selector}{{\n{css}\n}}\n"]
        if right_css and right_css != css:
            right_css = f"  background: {right_css}"
            if self.text_colour:
                right_css = f"{right_css};\n  color: {self.text_colour}"
            elif self.white_text:
                right_css = f"{right_css};\n  color: #fff"
            if self.stroke_colour:
                right_css = f"{right_css};\n  stroke: {self.stroke_colour}"
            styles.append(f"{selector}.right{{\n{right_css}\n}}\n")
        return styles


class VehicleFeature(models.Model):
    class Category(models.TextChoices):
        FEATURE = "feature", "Feature"
        ACCESSIBILITY = "accessibility", "Accessibility"

    name = models.CharField(max_length=255, unique=True)
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.FEATURE,
    )

    def __str__(self):
        return self.name

    class Meta:
        app_label = "vehicles"
        ordering = ("category", "name")


class VehicleNamePage(models.Model):
    name = models.CharField(max_length=255, unique=True, db_index=True)
    slug = AutoSlugField(populate_from="name", editable=True, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "vehicles"
        ordering = ("name",)
        constraints = [
            UniqueConstraint(
                Upper("name"),
                name="vehicles_vehicle_name_page_unique_name_upper",
            )
        ]
        verbose_name = "vehicle name page"
        verbose_name_plural = "vehicle name pages"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("vehicle_name_page_detail", args=(self.slug,))


class BusGroup(models.Model):
    title = models.CharField(max_length=255, unique=True, db_index=True)
    slug = AutoSlugField(populate_from="title", editable=True, unique=True)
    description = models.TextField(blank=True)
    header_background = ColourField(max_length=7, blank=True)
    header_foreground = ColourField(max_length=7, blank=True)
    accent_colour = ColourField(max_length=7, blank=True)
    banner = models.ImageField(upload_to="bus-groups/banners", blank=True, null=True)
    vehicles = models.ManyToManyField("Vehicle", blank=True, related_name="bus_groups")
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "vehicles"
        ordering = ("title",)
        constraints = [
            UniqueConstraint(
                Upper("title"),
                name="vehicles_bus_group_unique_title_upper",
            )
        ]
        verbose_name = "bus group"
        verbose_name_plural = "bus groups"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("bus_group_detail", args=(self.slug,))


def vehicle_slug(vehicle):
    base = f"{vehicle.operator_id} {vehicle.code.replace('_', ' ')}"
    if getattr(vehicle, "historical_fleet_id", None) and getattr(
        vehicle, "historical_fleet_year", None
    ):
        return f"{base} {vehicle.historical_fleet_year}"
    return base


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


@lru_cache(maxsize=1)
def missing_vehicle_field_names():
    columns = vehicle_db_columns()
    missing = []
    for field in Vehicle._meta.concrete_fields:
        column = getattr(field, "column", None)
        if column and column not in columns:
            missing.append(field.name)
    return tuple(missing)


def vehicle_compat_defer_fields(prefix=""):
    return tuple(f"{prefix}{name}" for name in missing_vehicle_field_names())


def current_vehicle_filters(**filters):
    columns = vehicle_db_columns()
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


class VehicleQuerySet(models.QuerySet):
    def with_schema_compat(self):
        missing = vehicle_compat_defer_fields()
        if missing:
            return self.defer(*missing)
        return self


class VehicleManager(models.Manager.from_queryset(VehicleQuerySet)):
    def get_queryset(self):
        return super().get_queryset().with_schema_compat()


class VehicleRelatedCompatQuerySet(models.QuerySet):
    def with_vehicle_schema_compat(self):
        missing = vehicle_compat_defer_fields("vehicle__")
        if missing:
            return self.defer(*missing)
        return self


class VehicleRelatedCompatManager(models.Manager.from_queryset(VehicleRelatedCompatQuerySet)):
    def get_queryset(self):
        return super().get_queryset().with_vehicle_schema_compat()


class Vehicle(models.Model):
    objects = VehicleManager()

    slug = AutoSlugField(populate_from=vehicle_slug, editable=True, unique=True)
    code = models.CharField(max_length=255)
    fleet_number = models.PositiveIntegerField(null=True, blank=True)
    fleet_code = models.CharField(max_length=24, blank=True)
    reg = models.CharField(max_length=24, blank=True)
    prev_registration = models.CharField(max_length=24, blank=True)
    external_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    is_manual = models.BooleanField(default=False)
    manual_updated_at = models.DateTimeField(null=True, blank=True)
    source = models.ForeignKey(DataSource, models.SET_NULL, null=True, blank=True)
    operator = models.ForeignKey(Operator, models.SET_NULL, null=True, blank=True)
    operated_by = models.ForeignKey(
        Operator,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="operated_vehicles",
        help_text="Operator that operates this vehicle (if different from the owner)",
    )
    vehicle_type = models.ForeignKey(
        VehicleType, models.SET_NULL, null=True, blank=True
    )
    colours = ColoursField(max_length=255, blank=True)
    livery = models.ForeignKey(Livery, models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255, blank=True)
    branding = models.CharField(max_length=255, blank=True)
    rear_advert = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    latest_journey = models.OneToOneField(
        "VehicleJourney",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="latest_vehicle",
    )
    latest_journey_data = models.JSONField(null=True, blank=True)
    features = models.ManyToManyField(VehicleFeature, blank=True)
    withdrawn = models.BooleanField(default=False)
    preserved = models.BooleanField(
        default=False,
        help_text="Keep this vehicle as a preserved record outside the active fleet list.",
    )
    preserved_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="preserved_vehicles",
        help_text="Individual user who preserves this vehicle.",
    )
    preservation_group = models.ForeignKey(
        PreservationGroup,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="preserved_vehicles",
        help_text="Preservation group that owns this vehicle.",
    )
    fleet_support_vehicle = models.BooleanField(
        default=False,
        help_text="Use for fleet support vehicles. This stays in sync with feature 9.",
    )
    vor = models.BooleanField(
        default=False,
        verbose_name="VOR",
        help_text="Vehicle off road.",
    )
    awaiting_delivery = models.BooleanField(
        default=False,
        help_text="Use for vehicles that are still awaiting delivery or entry into service.",
    )
    trainer_vehicle = models.BooleanField(
        default=False,
        help_text="Use for vehicles primarily assigned to training duties.",
    )
    demonstrator = models.BooleanField(
        default=False,
        help_text="Use for demonstrators so they appear in manufacturer demonstrator fleets.",
    )
    dvla_tax_status = models.CharField(
        max_length=32,
        blank=True,
        choices=DVLATaxStatus.choices,
    )
    dvla_mot_status = models.CharField(
        max_length=32,
        blank=True,
        choices=DVLAMotStatus.choices,
    )
    dvla_euro_status = models.CharField(max_length=32, blank=True)
    dvla_tax_status_checked_at = models.DateTimeField(null=True, blank=True)
    year_of_manufacture = models.PositiveIntegerField(null=True, blank=True)
    joined_fleet = models.CharField(
        max_length=7,
        blank=True,
        help_text="MM-YYYY format (e.g., 01-2024)",
    )
    left_fleet = models.CharField(
        max_length=7,
        blank=True,
        help_text="MM-YYYY format (e.g., 12-2024)",
    )
    previous_operators = models.JSONField(
        null=True,
        blank=True,
        help_text="List of previous operators with joined_fleet dates. Format: [{'operator_id': 123, 'joined_fleet': '01-2024'}]",
    )
    historical_fleet = models.ForeignKey(
        Operator,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="historical_vehicle_set",
    )
    historical_fleet_year = models.PositiveIntegerField(null=True, blank=True)
    historical_fleet_creator = models.CharField(max_length=255, blank=True)
    data = models.JSONField(null=True, blank=True)
    garage = models.ForeignKey(
        "bustimes.Garage", models.SET_NULL, null=True, blank=True
    )
    locked = models.BooleanField(default=False)
    advanced = models.JSONField(
        null=True,
        blank=True,
        default=dict,
        help_text="Advanced metadata for power users (historic owners, internal notes, etc.)"
    )

    @classmethod
    def missing_db_fields(cls):
        return missing_vehicle_field_names()

    def _missing_db_field_default(self, name):
        values = object.__getattribute__(self, "__dict__")
        if name in values:
            return values[name]
        field = object.__getattribute__(self, "_meta").get_field(name)
        return field.get_default()

    def __getattribute__(self, name):
        if (
            not name.startswith("_")
            and name not in {"missing_db_fields", "_missing_db_field_default"}
            and name in type(self).missing_db_fields()
        ):
            return object.__getattribute__(self, "_missing_db_field_default")(name)
        return super().__getattribute__(name)

    def is_spare_ticket_machine(self) -> bool:
        return self.notes == "Spare ticket machine"

    def is_editable(self) -> bool:
        if self.locked:
            return False
        # Vehicles remain editable regardless of withdrawn or preserved status
        # This allows legitimate improvements to historical records
        return True

    def save(self, *args, update_fields=None, **kwargs):
        if (
            update_fields is None or "fleet_number" in update_fields
        ) and self.fleet_number:
            if not self.fleet_code or (
                self.fleet_code.isdigit() and self.fleet_number != int(self.fleet_code)
            ):
                self.fleet_code = str(self.fleet_number)
                if update_fields is not None and "fleet_code" not in update_fields:
                    update_fields.append("fleet_code")

        if (update_fields is None or "fleet_code" in update_fields) and self.fleet_code:
            if not self.fleet_number and self.fleet_code.isdigit():
                self.fleet_number = int(self.fleet_code)
                if update_fields is not None and "fleet_number" not in update_fields:
                    update_fields.append("fleet_number")

        if update_fields is None and not self.reg:
            reg = re.match(r"^[A-Z]\w_?\d\d?[ _-]?[A-Z]{3}$", self.code)
            if reg:
                self.reg = re.sub("[-_ ]", "", self.code)
        elif update_fields is None or "reg" in update_fields:
            self.reg = self.reg.upper().replace(" ", "")

        if update_fields is None or "prev_registration" in update_fields:
            self.prev_registration = self.prev_registration.upper().replace(" ", "")

        # Vehicles in historical fleets should be marked as withdrawn
        if (update_fields is None or "historical_fleet" in update_fields) and self.historical_fleet_id:
            self.withdrawn = True
            if update_fields is not None and "withdrawn" not in update_fields:
                update_fields.append("withdrawn")

        # Fleet support vehicles must always carry feature 9.
        sync_fleet_support_feature = (
            "fleet_support_vehicle" not in self.missing_db_fields()
            and "features" not in self.missing_db_fields()
        )

        missing_fields = set(self.missing_db_fields())
        if missing_fields:
            if update_fields is not None:
                update_fields = [field for field in update_fields if field not in missing_fields]
                if not update_fields:
                    return
            elif not self._state.adding:
                update_fields = [
                    field.name
                    for field in self._meta.local_concrete_fields
                    if getattr(field, "column", None) in vehicle_db_columns()
                    and not field.primary_key
                ]

        super().save(*args, update_fields=update_fields, **kwargs)

        if sync_fleet_support_feature and self.pk and VehicleFeature.objects.filter(pk=18).exists():
            relation = self.features.through.objects.filter(
                vehicle_id=self.pk,
                vehiclefeature_id=18,
            )
            if self.fleet_support_vehicle:
                relation.get_or_create(
                    vehicle_id=self.pk,
                    vehiclefeature_id=18,
                )
            else:
                relation.delete()

    class Meta:
        indexes = [
            models.Index(Upper("fleet_code"), name="fleet_code"),
            models.Index(Upper("reg"), name="reg"),
            models.Index(fields=["operator", "withdrawn"], name="operator_withdrawn"),
        ]
        constraints = [
            models.UniqueConstraint(
                Upper("code"),
                "operator",
                condition=Q(preserved=False, historical_fleet__isnull=True),
                name="vehicle_operator_and_code_live",
            ),
            # Temporarily commented out due to CheckConstraint argument order issue
            # models.CheckConstraint(
            #     check=(
            #         Q(preserved_by_user__isnull=True)
            #         | Q(preservation_group__isnull=True)
            #     ),
            #     name="vehicle_single_preservation_owner",
            # ),
        ]

    def clean(self):
        super().clean()
        if self.preserved_by_user_id and self.preservation_group_id:
            raise ValidationError(
                {
                    "preserved_by_user": "Choose either an individual preservation owner or a preservation group, not both.",
                    "preservation_group": "Choose either a preservation group or an individual preservation owner, not both.",
                }
            )

    @property
    def preservation_owner(self):
        return self.preservation_group or self.preserved_by_user

    def __str__(self):
        fleet_code = self.fleet_code or self.fleet_number
        if self.reg:
            if fleet_code:
                reg = self.get_reg()
                if reg:
                    return f"{fleet_code} - {reg}"
                return str(fleet_code)
            return self.get_reg()
        if fleet_code:
            return str(fleet_code)
        return self.code.replace("_", " ")

    def get_next(self, order=""):
        lookup = "lt" if order == "-" else "gt"
        if self.operator:
            filter = {}
            if self.fleet_number:
                filter[f"fleet_number__{lookup}"] = self.fleet_number
                order_by = f"{order}fleet_number"
            elif self.fleet_code:
                filter[f"fleet_code__{lookup}"] = self.fleet_code
                order_by = f"{order}fleet_code"
            else:
                filter[f"code__{lookup}"] = self.code
                order_by = f"{order}code"

            return (
                self.operator.vehicle_set.filter(
                    **filter,
                    **current_vehicle_filters(
                        withdrawn=False,
                        preserved=False,
                    ),
                )
                .order_by(order_by)
                .first()
            )

    def get_previous(self):
        return self.get_next(order="-")

    def get_reg(self):
        if self.vehicle_type and self.vehicle_type.style == "train" and (self.fleet_number or self.fleet_code):
            return ""
        return format_reg(self.reg)

    def get_joined_fleet_display(self):
        if not self.joined_fleet:
            return ""
        try:
            month, year = self.joined_fleet.split("-")
            month_num = int(month)
            month_name = datetime.datetime(2024, month_num, 1).strftime("%B")
            return f"{month_name} {year}"
        except (ValueError, IndexError):
            return self.joined_fleet

    def get_features_by_category(self, category):
        return [feature for feature in self.features.all() if feature.category == category]

    def get_standard_features(self):
        return self.get_features_by_category(VehicleFeature.Category.FEATURE)

    def get_accessibility_features(self):
        return self.get_features_by_category(VehicleFeature.Category.ACCESSIBILITY)

    def get_feature_names(self):
        return ", ".join(feature.name for feature in self.get_standard_features())

    @property
    def accessibility_feature_names(self):
        return ", ".join(
            feature.name for feature in self.get_accessibility_features()
        )

    def data_get(self, key=None):
        label_map = {}
        if self.operator_id:
            label_map = {
                slug: name
                for slug, name in self.operator.vehicle_columns.values_list("slug", "name")
            }
            reverse_label_map = {name: slug for slug, name in label_map.items()}
        else:
            reverse_label_map = {}
        if not key:
            if self.prev_registration:
                data = {"Previous reg": self.prev_registration}
                if self.data:
                    data.update(self.data)
                return [
                    (label_map.get(key, key), self.data_get(label_map.get(key, key)))
                    for key in data
                ]
            if self.data:
                return [
                    (label_map.get(key, key), self.data_get(label_map.get(key, key)))
                    for key in self.data
                ]
            return ()
        if key == "Previous reg" and self.prev_registration:
            return ", ".join(format_reg(reg) for reg in self.prev_registration.split(","))
        if self.data:
            value = self.data.get(key)
            if value is None and key in reverse_label_map:
                value = self.data.get(reverse_label_map[key])
            if value:
                if key == "Previous reg":
                    return ", ".join(format_reg(reg) for reg in value.split(","))
                return value
        return ""

    def get_text_colour(self):
        if self.livery:
            if self.livery.white_text:
                return "#fff"
        elif self.colours:
            return get_text_colour(self.colours)

    def get_livery(self, direction=None):
        if self.livery:
            if direction is not None and direction < 180:
                return escape(self.livery.right_css)
            return escape(self.livery.left_css)

        colours = self.colours
        if colours and colours != "Other":
            colours = colours.split()
            if len(colours) > 1:
                self.colour = Counter(colours).most_common()[0][0]
            return get_css(colours, direction, self.livery and self.livery.horizontal)

    def get_absolute_url(self):
        return reverse("vehicle_detail", args=(self.slug or self.id,))

    def get_fleet_code_url(self):
        return self.get_absolute_url()

    def get_edit_url(self):
        return reverse("vehicle_edit", args=(self.slug or self.id,))

    def get_flickr_url(self):
        if self.reg:
            reg = self.get_reg()
            search = f'{self.reg} or "{reg}"'
            return f"https://www.flickr.com/search/?text={quote(search)}&sort=date-taken-desc"

    def get_flickr_link(self):
        if url := self.get_flickr_url():
            return format_html(
                '<a href="{}" target="_blank" rel="noopener">Flickr</a>', url
            )
        return ""

    get_flickr_link.short_description = "Flickr"

    def get_json(self):
        json = {
            "url": self.get_absolute_url(),
            "name": str(self),
        }

        features = getattr(self, "feature_names", self.get_feature_names())
        if self.vehicle_type:
            vehicle_type = self.vehicle_type.style.capitalize()
            if vehicle_type:
                if features:
                    features = f"{vehicle_type}<br>{features}"
                else:
                    features = vehicle_type
        if features:
            json["features"] = features

        if self.livery_id:
            json["livery"] = self.livery_id
            if self.livery.livery_type == 'svg' and self.livery.svg:
                json["livery_type"] = 'svg'
                json["livery_svg_url"] = self.livery.svg.url
            else:
                json["css"] = self.livery.left_css
                json["right_css"] = self.livery.right_css
                if self.livery.text_colour:
                    json["text_colour"] = self.livery.text_colour
                elif self.livery.white_text:
                    json["text_colour"] = "#fff"
        elif self.colours:
            json["css"] = self.get_livery()
            json["right_css"] = self.get_livery(90)
            json["text_colour"] = self.get_text_colour()
        if colour := getattr(self, "colour", None):
            json["colour"] = colour
        return json

    def get_statuses(self):
        statuses = []
        if self.preserved:
            statuses.append("Preserved")
        if self.fleet_support_vehicle:
            statuses.append("Fleet Support Vehicle")
        if self.vor:
            statuses.append("VOR")
        if self.awaiting_delivery:
            statuses.append("Awaiting delivery")
        if self.trainer_vehicle:
            statuses.append("Trainer vehicle")
        if self.demonstrator:
            statuses.append("Demonstrator")
        return statuses

    def get_fleet_row_class(self):
        classes = []
        if self.vor:
            classes.append("fleet-row--vor")
        elif self.awaiting_delivery:
            classes.append("fleet-row--awaiting-delivery")
        elif self.demonstrator:
            classes.append("fleet-row--demonstrator")
        elif self.trainer_vehicle:
            classes.append("fleet-row--trainer")
        elif self.fleet_support_vehicle:
            classes.append("fleet-row--fleet-support")
        if self.preserved:
            classes.append("fleet-row--preserved")
        return " ".join(classes)

    def has_sorn_vor_suggestion(self):
        return self.dvla_tax_status == DVLATaxStatus.SORN and not self.vor


class VehicleCode(models.Model):
    objects = VehicleRelatedCompatManager()

    code = models.CharField(max_length=100)
    scheme = models.CharField(max_length=24)
    vehicle = models.ForeignKey(Vehicle, models.CASCADE)

    def __str__(self):
        return f"{self.scheme} {self.code}"

    class Meta:
        app_label = "vehicles"
        constraints = [
            UniqueConstraint(
                fields=["code", "scheme"],
                name="unique_vehicle_code",
            ),
        ]
        indexes = [models.Index(fields=("code", "scheme"))]


class VehicleRevisionFeature(models.Model):
    feature = models.ForeignKey(VehicleFeature, models.CASCADE)
    revision = models.ForeignKey("VehicleRevision", models.CASCADE)
    add = models.BooleanField(default=True)

    def __str__(self):
        if self.add:
            fmt = "<ins>{}</ins>"
        else:
            fmt = "<del>{}</del>"
        return format_html(fmt, self.feature)


class VehicleReview(models.Model):
    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        PENDING = "pending", "Pending moderation"
        HIDDEN = "hidden", "Hidden"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.CASCADE, related_name="vehicle_reviews"
    )
    vehicle = models.ForeignKey(Vehicle, models.CASCADE, related_name="reviews")
    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("5.0"))],
    )
    message = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PUBLISHED, db_index=True
    )
    moderation_notes = models.TextField(blank=True)
    flagged_terms = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "vehicles"
        ordering = ("-updated_at", "-created_at")
        permissions = [
            ("delete_review", "Can delete review"),
        ]

    def __str__(self):
        return f"{self.user} on {self.vehicle}"

    def get_rating_display_stars(self):
        filled_halves = int(self.rating * 2)
        full_stars = filled_halves // 2
        has_half = filled_halves % 2
        return "★" * full_stars + ("½" if has_half else "") + "☆" * (5 - full_stars - has_half)

    def get_rating_percentage(self):
        return float(self.rating) / 5 * 100

    @property
    def is_public(self):
        return self.status == self.Status.PUBLISHED


class VehicleReviewReport(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    review = models.ForeignKey(
        VehicleReview, models.CASCADE, related_name="reports"
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="vehicle_review_reports",
    )
    reason = models.TextField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "vehicles"
        ordering = ("-created_at",)

    def __str__(self):
        return f"Report on {self.review}"


class ReviewBlockedPhrase(models.Model):
    phrase = models.CharField(max_length=255, unique=True)
    normalized_phrase = models.CharField(max_length=255, editable=False, db_index=True)
    notes = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "vehicles"
        ordering = ("phrase",)
        verbose_name = "review blocked phrase"
        verbose_name_plural = "review blocked phrases"

    def __str__(self):
        return self.phrase

    def save(self, *args, **kwargs):
        from .moderation import normalize_review_text

        self.normalized_phrase = normalize_review_text(self.phrase)
        super().save(*args, **kwargs)


class VehicleRevision(models.Model):
    objects = VehicleRelatedCompatManager()

    vehicle = models.ForeignKey(Vehicle, models.CASCADE)

    from_operator = models.ForeignKey(
        Operator, models.SET_NULL, null=True, blank=True, related_name="revision_from"
    )
    to_operator = models.ForeignKey(
        Operator, models.SET_NULL, null=True, blank=True, related_name="revision_to"
    )
    from_operated_by = models.ForeignKey(
        Operator, models.SET_NULL, null=True, blank=True, related_name="revision_operated_by_from"
    )
    to_operated_by = models.ForeignKey(
        Operator, models.SET_NULL, null=True, blank=True, related_name="revision_operated_by_to"
    )
    from_type = models.ForeignKey(
        VehicleType,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="revision_from",
    )
    to_type = models.ForeignKey(
        VehicleType, models.SET_NULL, null=True, blank=True, related_name="revision_to"
    )
    from_livery = models.ForeignKey(
        Livery, models.SET_NULL, null=True, blank=True, related_name="revision_from"
    )
    to_livery = models.ForeignKey(
        Livery, models.SET_NULL, null=True, blank=True, related_name="revision_to"
    )
    from_garage = models.ForeignKey(
        "bustimes.Garage",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="revision_from",
    )
    to_garage = models.ForeignKey(
        "bustimes.Garage",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="revision_to",
    )

    features = models.ManyToManyField(
        VehicleFeature, blank=True, through=VehicleRevisionFeature
    )

    changes = models.JSONField(null=True, blank=True)
    message = models.TextField(null=True, blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved",
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_revisions",
    )
    created_at = models.DateTimeField()
    approved_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    pending = models.BooleanField(default=False)
    disapproved = models.BooleanField(default=False)
    disapproved_reason = models.TextField(null=True, blank=True)
    edit_reason = models.TextField(null=True, blank=True)

    class Meta:
        app_label = "vehicles"
        constraints = [
            UniqueConstraint(
                fields=["vehicle", "to_operator"],
                condition=Q(pending=True),
                name="unique_pending_operator",
            ),
            UniqueConstraint(
                fields=["vehicle", "to_operated_by"],
                condition=Q(pending=True),
                name="unique_pending_operated_by",
            ),
            UniqueConstraint(
                fields=["vehicle", "to_type"],
                condition=Q(pending=True),
                name="unique_pending_type",
            ),
            UniqueConstraint(
                fields=["vehicle", "to_livery"],
                condition=Q(pending=True),
                name="unique_pending_livery",
            ),
            UniqueConstraint(
                fields=["vehicle", "to_garage"],
                condition=Q(pending=True),
                name="unique_pending_garage",
            ),
        ]

    def __str__(self):
        return ", ".join(
            f"{key}: {before} → {after}"
            for key, before, after in self.list_changes(html=False)
        )

    def list_changes(self, html=True):
        for field in ("operator", "operated_by", "type", "livery", "garage"):
            if getattr(self, f"from_{field}_id") or getattr(self, f"to_{field}_id"):
                if getattr(__class__, f"from_{field}").is_cached(self):
                    before = getattr(self, f"from_{field}")
                    after = getattr(self, f"to_{field}")

                    if field == "livery":
                        if before:
                            before = format_html(
                                '<span class="livery" style="background:{}"></span>{}',
                                before.left_css,
                                before.name,
                            )
                        if after:
                            after = format_html(
                                '<span class="livery" style="background:{}"></span>{}',
                                after.left_css,
                                after.name,
                            )
                    if field == "garage":
                        # Get all garages for the operator
                        from bustimes.models import Garage
                        operator = self.to_operator or self.from_operator
                        if operator:
                            all_garages = Garage.objects.filter(operators=operator).order_by('name')
                            if all_garages.exists():
                                garage_list = ", ".join(g.name for g in all_garages)
                                if html:
                                    garage_list = f" ({garage_list})"
                                if after:
                                    after = f"{after}{garage_list}"
                                elif before:
                                    before = f"{before}{garage_list}"
                else:
                    before = getattr(self, f"from_{field}_id")
                    after = getattr(self, f"to_{field}_id")
                yield (field, before, after)
        if self.changes:
            for key in self.changes:
                before, after = self.changes[key].split("\n+")
                before = before[1:]
                if key == "colours" and html:
                    if before and before != "Other":
                        before = format_html(
                            '<span class="livery" style="background:{}"></span>',
                            get_css(before.split()),
                        )
                    if after and after != "Other":
                        after = format_html(
                            '<span class="livery" style="background:{}"></span>',
                            get_css(after.split()),
                        )
                if key == "withdrawn":
                    if after == "Yes":
                        yield ("removed from list", "", "")
                    else:
                        yield ("added to list", "", "")
                elif key == "preserved":
                    if after == "Yes":
                        yield ("marked preserved", "", "")
                    else:
                        yield ("cleared preserved", "", "")
                else:
                    yield (key, before, after)

    def revert(self):
        """Revert various values to how they were before the revision"""
        vehicle = self.vehicle
        fields = []

        for key, vehicle_key in (
            ("operator", "operator"),
            ("operated_by", "operated_by"),
            ("type", "vehicle_type"),
            ("livery", "livery"),
            ("garage", "garage"),
        ):
            before = getattr(self, f"from_{key}_id")
            after = getattr(self, f"to_{key}_id")
            if before or after:
                if getattr(vehicle, f"{vehicle_key}_id") == after:
                    setattr(vehicle, f"{vehicle_key}_id", before)
                    fields.append(vehicle_key)

        if self.changes:
            for key in self.changes:
                before, after = self.changes[key].split("\n+")
                before = before[1:]
                if key == "reg" or key == "name":
                    if getattr(vehicle, key) == after:
                        setattr(vehicle, key, before)
                        fields.append("reg")
                elif key == "previous reg":
                    if vehicle.prev_registration == after:
                        vehicle.prev_registration = before
                        fields.append("prev_registration")
                elif key in ("withdrawn", "preserved"):
                    if getattr(vehicle, key) and after == "Yes":
                        setattr(vehicle, key, False)
                        fields.append(key)
                elif key == "fleet number":
                    vehicle.fleet_code = before
                    if before.isdigit():
                        vehicle.fleet_number = int(vehicle.fleet_number)
                    else:
                        vehicle.fleet_number = None
                    fields += ["fleet_number", "fleet_code"]
                else:
                    yield f"vehicle {vehicle.id} {key} not reverted"

        if fields:
            self.vehicle.save(update_fields=fields)
            yield f"vehicle {vehicle.id} reverted {fields}"


class VehicleJourney(models.Model):
    objects = VehicleRelatedCompatManager()

    datetime = models.DateTimeField()
    date = models.DateField()
    service = models.ForeignKey(
        Service, models.SET_NULL, null=True, blank=True, db_index=False
    )
    route_name = models.CharField(max_length=64, blank=True)
    source = models.ForeignKey(DataSource, models.CASCADE)
    vehicle = models.ForeignKey(
        Vehicle, models.CASCADE, null=True, blank=True, db_index=False
    )
    code = models.CharField(max_length=255, blank=True)
    destination = models.CharField(max_length=255, blank=True)
    direction = models.CharField(max_length=13, blank=True)
    trip = models.ForeignKey(
        "bustimes.Trip", models.SET_NULL, null=True, blank=True, db_index=False
    )
    # trip_matched = models.BooleanField(default=True)
    # block = models.ForeignKey("bustimes.Block", models.SET_NULL, null=True, blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)

    def get_absolute_url(self):
        # TODO: change to "/journeys/{self.id}" (actually using `reverse()`)
        return f"/vehicles/{self.vehicle_id}?date={self.date}#journey-{self.id}"

    def __str__(self):
        when = f"{self.datetime:%-d %b %y %H:%M} {self.route_name} {self.code} {self.direction}"
        if self.destination:
            when = f"{when} to {self.destination}"
        return when

    class Meta:
        app_label = "vehicles"
        ordering = ("id",)
        indexes = [
            models.Index("service", "date", name="vehiclejourney_service_date"),
            models.Index(
                "vehicle",
                "date",
                name="vehiclejourney_vehicle_date",
                condition=Q(vehicle__isnull=False),
            ),
            models.Index(
                "trip",
                "date",
                name="vehiclejourney_trip_date",
                condition=Q(trip__isnull=False),
            ),
            models.Index(
                "route_name",
                "date",
                name="route_name__date",
                condition=Q(service__isnull=True),
            ),
        ]

    def get_redis_key(self):
        return self.uuid.bytes

    get_trip = get_trip

    def get_trip_block_url(self):
        url = reverse("block_detail", args=(self.trip_id,))
        return f"{url}?date={self.date}"

    def get_service_link(self):
        if self.service:
            slug = self.service.slug
        else:
            slug = f"{self.vehicle.operator_id}:{self.route_name}"
        return (
            reverse("service_vehicles", args=(slug,)) + "?date=" + self.date.isoformat()
        )


class VehicleLocation:
    """This used to be a model,
    is no longer stored in the database
    but this code is still here for historical reasons
    """

    def __init__(self, latlong, heading=None, delay=None, occupancy=None, block=None):
        self.latlong = latlong
        self.heading = heading
        self.delay = delay
        self.occupancy = occupancy
        self.seated_occupancy = None
        self.seated_capacity = None
        self.wheelchair_occupancy = None
        self.wheelchair_capacity = None
        self.occupancy_thresholds = None
        self.block = block
        self.tfl_code = None

    def __str__(self):
        return f"{self.datetime:%-d %b %Y %H:%M:%S}"

    class Meta:
        ordering = ("id",)

    def get_appendage(self):
        delay = self.delay
        if delay is not None:
            delay = round(delay.total_seconds() / 60)

        if self.heading is None or type(self.heading) is int:
            heading = self.heading
        elif type(self.heading) is str:
            if self.heading.isdigit():
                heading = int(self.heading)
            elif self.heading:
                heading = round(float(self.heading))
            else:
                heading = None
        else:
            heading = round(self.heading)

        return self.journey.get_redis_key(), struct.pack(
            "I 2f ?h ?h",
            round(self.datetime.timestamp()),
            self.latlong.x,
            self.latlong.y,
            heading is not None,
            heading or 0,
            delay is not None,
            delay or 0,
        )

    @staticmethod
    def decode_appendage(location):
        location = struct.unpack("I 2f ?h ?h", location)
        return {
            "id": location[0],
            "coordinates": location[1:3],
            "delta": (location[5] or None) and location[6],
            "direction": (location[3] or None) and location[4],
            "datetime": timezone.localtime(
                datetime.datetime.fromtimestamp(location[0], datetime.timezone.utc)
            ),
        }

    def get_redis_json(self):
        journey = self.journey

        json = {
            "id": self.id,  # (same as vehicle id)
            "journey_id": journey.id,
            "coordinates": self.latlong.coords,
            "heading": self.heading,
            "datetime": timezone.localtime(self.datetime),
            "destination": journey.destination,
            "block": self.block,
        }

        if self.delay is not None:
            json["delay"] = self.delay.total_seconds()

        if self.tfl_code:
            json["tfl_code"] = self.tfl_code
        if journey.trip_id:
            json["trip_id"] = journey.trip_id
        if journey.service_id:
            json["service_id"] = journey.service_id
        if journey.route_name:
            json["service"] = {"line_name": journey.route_name}

        if self.seated_occupancy is not None and self.seated_capacity is not None:
            if self.occupancy == "Full":
                json["seats"] = self.occupancy
            else:
                json["seats"] = f"{self.seated_capacity - self.seated_occupancy} free"
        elif self.occupancy:
            json["seats"] = self.occupancy
        if self.wheelchair_occupancy is not None and self.wheelchair_capacity:
            if self.wheelchair_occupancy < self.wheelchair_capacity:
                json["wheelchair"] = "free"
            else:
                json["wheelchair"] = "occupied"

        return json


class HistoricalVehicle(models.Model):
    slug = AutoSlugField(populate_from=vehicle_slug, editable=True, unique=True)
    code = models.CharField(max_length=255)
    fleet_number = models.PositiveIntegerField(null=True, blank=True)
    fleet_code = models.CharField(max_length=24, blank=True)
    reg = models.CharField(max_length=24, blank=True)
    prev_registration = models.CharField(max_length=24, blank=True)
    operator = models.ForeignKey(Operator, models.SET_NULL, null=True, blank=True)
    operated_by = models.ForeignKey(
        Operator,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="operated_historical_vehicles",
        help_text="Operator that operates this vehicle (if different from the owner)",
    )
    vehicle_type = models.ForeignKey(
        VehicleType, models.SET_NULL, null=True, blank=True
    )
    colours = ColoursField(max_length=255, blank=True)
    livery = models.ForeignKey(Livery, models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=255, blank=True)
    branding = models.CharField(max_length=255, blank=True)
    rear_advert = models.CharField(max_length=255, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    features = models.ManyToManyField(VehicleFeature, blank=True)
    fleet_support_vehicle = models.BooleanField(default=False)
    trainer_vehicle = models.BooleanField(default=False)
    year_of_manufacture = models.PositiveIntegerField(null=True, blank=True)
    joined_fleet_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the vehicle joined the fleet (dd-mm-yyyy)",
    )
    left_fleet_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date the vehicle left the fleet (dd-mm-yyyy)",
    )
    previous_operators = models.JSONField(
        null=True,
        blank=True,
        help_text="List of previous operators with joined_fleet dates. Format: [{'operator_id': 123, 'joined_fleet': '01-2024'}]",
    )
    data = models.JSONField(null=True, blank=True)
    garage = models.ForeignKey(
        "bustimes.Garage", models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        fleet_code = self.fleet_code or self.fleet_number
        if self.reg:
            if fleet_code:
                reg = self.get_reg()
                if reg:
                    return f"{fleet_code} - {reg}"
                return str(fleet_code)
            return self.get_reg()
        if fleet_code:
            return str(fleet_code)
        return self.code.replace("_", " ")

    def get_reg(self):
        if self.vehicle_type and self.vehicle_type.style == "train" and (self.fleet_number or self.fleet_code):
            return ""
        return format_reg(self.reg)

    def get_absolute_url(self):
        return reverse("historical_vehicle_detail", args=(self.slug or self.id,))

    class Meta:
        app_label = "vehicles"
        ordering = ("fleet_number", "fleet_code", "reg", "id")
        indexes = [
            models.Index(Upper("fleet_code"), name="historical_fleet_code"),
            models.Index(Upper("reg"), name="historical_reg"),
        ]


class SiriSubscription(models.Model):
    name = models.CharField(
        max_length=64,
        blank=True,
        unique=True,
        help_text="There should be a DataSource with the same name as this",
    )
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    sample = models.TextField(null=True, blank=True)
    producer_url = models.URLField(null=True, blank=True, max_length=64)
    username = models.CharField(null=True, blank=True, max_length=64)
    password = models.CharField(null=True, blank=True, max_length=64)
    requestor_ref = models.CharField(null=True, blank=True, max_length=64)

    def __str__(self):
        return self.name

    def get_status_key(self):
        return f"{self.name.replace(' ', '_')}_status"

    def get_absolute_url(self):
        return reverse("siri_post", args=(self.uuid,))
