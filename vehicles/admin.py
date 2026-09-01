from functools import lru_cache

from django import forms
from django.forms import ModelForm, Textarea, TextInput
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import models as django_models
from django.db.models import Exists, OuterRef, Q
from django.db import IntegrityError, connection
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin
from sql_util.utils import SubqueryCount

from busstops.forms import FleetImportForm
from busstops.fleet_imports import (
    build_livery_mapping_rows,
    collect_livery_mappings,
    commit_mass_rows,
    parse_mass_rows,
    rows_text_from_upload,
)
from fleet.completion import bulk_log_vehicles_for_user
from fleet.exporters.xlsx import build_basic_fleet_workbook, workbook_bytes
from busstops.models import Manufacturer, Operator
from . import models
from bustimes.admin import log_change

UserModel = get_user_model()


class VehicleAdminForm(forms.ModelForm):
    class Meta:
        model = models.Vehicle
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("preserved_by_user") and cleaned_data.get("preservation_group"):
            raise forms.ValidationError(
                "Choose either an individual preservation owner or a preservation group, not both."
            )
        return cleaned_data


@lru_cache(maxsize=1)
def vehicle_db_columns():
    try:
        with connection.cursor() as cursor:
            return {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, models.Vehicle._meta.db_table
                )
            }
    except Exception:
        return {
            field.column
            for field in models.Vehicle._meta.fields
            if getattr(field, "column", None)
        }


@lru_cache(maxsize=1)
def missing_vehicle_field_names():
    columns = vehicle_db_columns()
    missing = []
    for field in models.Vehicle._meta.concrete_fields:
        column = getattr(field, "column", None)
        if column and column not in columns:
            missing.append(field.name)
    return tuple(missing)


def apply_vehicle_schema_compat(queryset, prefix=""):
    missing = missing_vehicle_field_names()
    if missing:
        queryset = queryset.defer(*(f"{prefix}{name}" for name in missing))
    return queryset


@admin.register(models.VehicleTypeGroup)
class VehicleTypeGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "manufacturer")
    list_filter = ("manufacturer",)
    search_fields = ("name", "manufacturer__name")
    autocomplete_fields = ("manufacturer",)


@admin.register(models.VehicleType)
class VehicleTypeAdmin(admin.ModelAdmin):
    search_fields = ("name", "manufacturer__name", "vehicle_group__name")
    list_filter = (
        "manufacturer",
        "vehicle_group",
        "active_production",
        "style",
        "fuel",
        "company",
    )
    list_display = (
        "id",
        "name",
        "manufacturer",
        "vehicle_group",
        "active_production",
        "vehicles",
        "style",
        "fuel",
        "company",
    )
    list_editable = ("name", "active_production", "style", "fuel", "company")
    autocomplete_fields = ("manufacturer", "vehicle_group")
    actions = [
        "merge",
        "assign_to_manufacturer",
        "remove_from_manufacturer",
        "assign_to_vehicle_group",
        "remove_from_vehicle_group",
    ]

    @admin.display(ordering="vehicles")
    def vehicles(self, obj):
        return obj.vehicles

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            return queryset.annotate(vehicles=SubqueryCount("vehicle"))
        return queryset

    def save_model(self, request, obj, form, change):
        if request.user.is_superuser:
            obj.is_manual = True
            obj.manual_updated_at = timezone.now()
        super().save_model(request, obj, form, change)

    def _bulk_assign_related(
        self, request, queryset, form_class, field_name, template_title, submit_label
    ):
        selected = request.POST.getlist(ACTION_CHECKBOX_NAME)
        if "apply" in request.POST:
            form = form_class(request.POST)
            if form.is_valid():
                target = form.cleaned_data[field_name]
                updated = queryset.update(
                    **{
                        field_name: target,
                        "is_manual": True,
                        "manual_updated_at": timezone.now(),
                    }
                )
                self.message_user(
                    request,
                    f"Updated {updated} vehicle type{'s' if updated != 1 else ''}.",
                    level=messages.SUCCESS,
                )
                return None
        else:
            form = form_class()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "queryset": queryset.order_by("name"),
            "form": form,
            "title": template_title,
            "submit_label": submit_label,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "selected": selected,
            "action_name": request.POST.get("action", ""),
        }
        return TemplateResponse(
            request,
            "admin/vehicles/vehicletype/bulk_assign.html",
            context,
        )

    @admin.action(description="Add selected vehicle types to a Manufactor")
    def assign_to_manufacturer(self, request, queryset):
        class VehicleTypeBulkAssignManufacturerForm(forms.Form):
            manufacturer = forms.ModelChoiceField(
                queryset=Manufacturer.objects.order_by("name"),
                required=True,
                label="Manufactor",
                help_text="Choose the manufactor to apply to all selected vehicle types.",
            )

        return self._bulk_assign_related(
            request,
            queryset,
            VehicleTypeBulkAssignManufacturerForm,
            "manufacturer",
            "Assign selected vehicle types to a manufactor",
            "Apply manufactor",
        )

    @admin.action(description="Remove selected vehicle types from their Manufactor")
    def remove_from_manufacturer(self, request, queryset):
        updated = queryset.update(
            manufacturer=None,
            is_manual=True,
            manual_updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"Removed manufactor from {updated} vehicle type{'s' if updated != 1 else ''}.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Add selected vehicle types to a vehicle group")
    def assign_to_vehicle_group(self, request, queryset):
        class VehicleTypeBulkAssignVehicleGroupForm(forms.Form):
            vehicle_group = forms.ModelChoiceField(
                queryset=models.VehicleTypeGroup.objects.select_related("manufacturer").order_by(
                    "manufacturer__name", "name"
                ),
                required=True,
                label="Vehicle group",
                help_text="Choose the vehicle group to apply to all selected vehicle types.",
            )

        return self._bulk_assign_related(
            request,
            queryset,
            VehicleTypeBulkAssignVehicleGroupForm,
            "vehicle_group",
            "Assign selected vehicle types to a vehicle group",
            "Apply vehicle group",
        )

    @admin.action(description="Remove selected vehicle types from their vehicle group")
    def remove_from_vehicle_group(self, request, queryset):
        updated = queryset.update(
            vehicle_group=None,
            is_manual=True,
            manual_updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"Removed vehicle group from {updated} vehicle type{'s' if updated != 1 else ''}.",
            level=messages.SUCCESS,
        )

    def merge(self, request, queryset):
        first = queryset[0]
        models.Vehicle.objects.filter(vehicle_type__in=queryset).update(
            vehicle_type=first
        )
        models.VehicleRevision.objects.filter(from_type__in=queryset).update(
            from_type=first
        )
        models.VehicleRevision.objects.filter(to_type__in=queryset).update(
            to_type=first
        )


@admin.register(models.VehicleNamePage)
class VehicleNamePageAdmin(admin.ModelAdmin):
    list_display = ("name", "modified_at")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "description":
            formfield.widget.attrs.setdefault("rows", 8)
        return formfield


@admin.register(models.BusGroup)
class BusGroupAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "modified_at")
    search_fields = (
        "title",
        "description",
    )
    prepopulated_fields = {"slug": ("title",)}
    fieldsets = (
        (None, {"fields": ("title", "slug", "description", "event_date", "event_end_date")}),
        (
            "Branding",
            {
                "fields": (
                    "banner",
                    "header_background",
                    "header_foreground",
                    "accent_colour",
                )
            },
        ),
    )


class VehicleAdminForm(ModelForm):
    class Meta:
        widgets = {
            "fleet_number": TextInput(attrs={"style": "width: 4em"}),
            "fleet_code": TextInput(attrs={"style": "width: 4em"}),
            "reg": TextInput(attrs={"style": "width: 8em"}),
            "branding": TextInput(attrs={"style": "width: 8em"}),
            "name": TextInput(attrs={"style": "width: 8em"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "operator" in self.fields and "garage" in self.fields:
            operator = self.instance.operator if self.instance.pk else None
            if operator:
                self.fields["garage"].queryset = self.fields["garage"].queryset.filter(operators=operator)
            else:
                self.fields["garage"].queryset = self.fields["garage"].queryset.none()


class VehicleBulkAssignLiveryForm(forms.Form):
    livery = forms.ModelChoiceField(
        queryset=models.Livery.objects.order_by("name"),
        required=False,
        help_text="Choose the livery to apply to all selected vehicles. Leave blank to clear it.",
    )


class VehicleBulkSetBrandingForm(forms.Form):
    branding = forms.CharField(
        required=False,
        widget=TextInput(attrs={"style": "width: 24em"}),
        help_text="Set the branding text for all selected vehicles. Leave blank to clear it.",
    )


class VehicleBulkAssignFeaturesForm(forms.Form):
    class Mode(django_models.TextChoices):
        ADD = "add", "Add selected features"
        REPLACE = "replace", "Replace with selected features"
        REMOVE = "remove", "Remove selected features"

    mode = forms.ChoiceField(
        choices=Mode.choices,
        initial=Mode.ADD,
        help_text="Choose how the selected features should be applied.",
    )
    features = forms.ModelMultipleChoiceField(
        queryset=models.VehicleFeature.objects.order_by("category", "name"),
        required=False,
        help_text="You can choose both accessibility and regular features here.",
    )


class VehicleBulkLogUserForm(forms.Form):
    user = forms.ModelChoiceField(
        queryset=UserModel.objects.order_by("display_name", "username", "email"),
        required=True,
        help_text="Choose which user should receive ride logs for the selected vehicles.",
    )


class VehicleBulkEditForm(forms.Form):
    fleet_number = forms.IntegerField(required=False, help_text="Set fleet number. Leave blank to keep current.")
    prev_registration = forms.CharField(required=False, max_length=24, help_text="Set previous registration. Leave blank to keep current.")
    vehicle_type = forms.ModelChoiceField(
        queryset=models.VehicleType.objects.order_by("name"),
        required=False,
        help_text="Set vehicle type. Leave blank to keep current.",
    )
    colours = forms.CharField(required=False, help_text="Set colours. Leave blank to keep current.")
    livery = forms.ModelChoiceField(
        queryset=models.Livery.objects.order_by("name"),
        required=False,
        help_text="Set livery. Leave blank to keep current.",
    )
    name = forms.CharField(required=False, max_length=255, help_text="Set name. Leave blank to keep current.")
    branding = forms.CharField(required=False, max_length=255, help_text="Set branding. Leave blank to keep current.")
    rear_advert = forms.CharField(required=False, max_length=255, help_text="Set rear advert. Leave blank to keep current.")
    notes = forms.CharField(required=False, max_length=255, help_text="Set notes. Leave blank to keep current.")
    withdrawn = forms.BooleanField(required=False, help_text="Mark as withdrawn")
    preserved = forms.BooleanField(required=False, help_text="Mark as preserved")
    fleet_support_vehicle = forms.BooleanField(required=False, help_text="Mark as fleet support vehicle")
    vor = forms.BooleanField(required=False, help_text="Mark as VOR (Vehicle Off Road)")
    awaiting_delivery = forms.BooleanField(required=False, help_text="Mark as awaiting delivery")
    trainer_vehicle = forms.BooleanField(required=False, help_text="Mark as trainer vehicle")
    demonstrator = forms.BooleanField(required=False, help_text="Mark as demonstrator")
    year_of_manufacture = forms.IntegerField(required=False, help_text="Set year of manufacture. Leave blank to keep current.")
    historical_fleet = forms.ModelChoiceField(
        queryset=Operator.objects.order_by("name"),
        required=False,
        help_text="Set historical fleet. Leave blank to keep current.",
    )
    historical_fleet_year = forms.IntegerField(required=False, help_text="Set historical fleet year. Leave blank to keep current.")
    historical_fleet_creator = forms.CharField(required=False, max_length=255, help_text="Set historical fleet creator. Leave blank to keep current.")
    locked = forms.BooleanField(required=False, help_text="Lock vehicles")


def user(obj):
    return format_html(
        '<a href="{}">{}</a>',
        reverse("admin:accounts_user_change", args=(obj.user_id,)),
        obj.user,
    )


class VehicleCodeInline(admin.TabularInline):
    model = models.VehicleCode


class DuplicateVehicleFilter(admin.SimpleListFilter):
    title = "duplicate"
    parameter_name = "duplicate"

    def lookups(self, request, model_admin):
        return (
            ("reg", "same reg"),
            ("operator", "same reg and operator"),
            ("fleet_code", "same fleet code"),
            ("code", "same code"),
        )

    def queryset(self, request, queryset):
        if value := self.value():
            duplicates = models.Vehicle.objects.filter(~Q(id=OuterRef("id")))
            if value == "code":
                duplicates = duplicates.filter(code__iexact=OuterRef("code"))
            elif value == "fleet_code":
                duplicates = duplicates.filter(code__iexact=OuterRef("fleet_code"))
            else:
                # reg
                duplicates = duplicates.filter(reg__iexact=OuterRef("reg"))
                # reg and operator
                if value == "operator":
                    duplicates = duplicates.filter(operator=OuterRef("operator"))

            queryset = queryset.filter(~Q(reg__iexact=""), Exists(duplicates))

        return queryset


@admin.register(models.Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    form = VehicleAdminForm
    change_list_template = "admin/vehicles/vehicle/change_list.html"
    list_display = (
        "code",
        "fleet_number",
        "fleet_code",
        "reg",
        "prev_registration",
        "operator",
        "operated_by",
        "vehicle_type",
        "get_flickr_link",
        "withdrawn",
        "preserved",
        "preserved_by_user",
        "preservation_group",
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
        "last_seen",
        "joined_fleet",
        "left_fleet",
        "previous_operators",
        "livery",
        "colours",
        "branding",
        "name",
        "notes",
        "data",
        "advanced",
    )
    list_filter = (
        DuplicateVehicleFilter,
        "withdrawn",
        "preserved",
        "preservation_group",
        ("preserved_by_user", admin.RelatedOnlyFieldListFilter),
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
        "features",
        "vehicle_type",
        ("source", admin.RelatedOnlyFieldListFilter),
        ("operator", admin.RelatedOnlyFieldListFilter),
        ("operated_by", admin.RelatedOnlyFieldListFilter),
        ("livery", admin.RelatedOnlyFieldListFilter),
    )
    list_select_related = [
        "operator",
        "operated_by",
        "livery",
        "vehicle_type",
        "latest_journey",
        "preservation_group",
        "preserved_by_user",
    ]
    list_editable = (
        "fleet_number",
        "fleet_code",
        "reg",
        "prev_registration",
        "operator",
        "joined_fleet",
        "left_fleet",
        "branding",
        "name",
        "notes",
    )
    autocomplete_fields = ("vehicle_type", "livery", "operator", "operated_by")
    raw_id_fields = (
        "source",
        "latest_journey",
        "preserved_by_user",
        "preservation_group",
    )
    search_fields = ("code", "fleet_code", "reg")
    ordering = ("-id",)
    actions = (
        "copy_livery",
        "copy_type",
        "make_livery",
        "mass_change_livery",
        "mass_change_branding",
        "mass_assign_features",
        "mass_log_vehicles",
        "mass_edit",
        "deduplicate",
        "merge_all_selected",
        "spare_ticket_machine",
        "preserve",
        "unpreserve",
        "lock",
        "unlock",
        "export_basic_fleet",
        "export_advanced_fleet",
    )
    inlines = [VehicleCodeInline]
    readonly_fields = ["latest_journey_data"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "code",
                    "slug",
                    "fleet_number",
                    "fleet_code",
                    "reg",
                    "prev_registration",
                    "operator",
                    "operated_by",
                    "vehicle_type",
                    "livery",
                    "colours",
                    "branding",
                    "rear_advert",
                    "name",
                    "notes",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "withdrawn",
                    "preserved",
                    "preserved_by_user",
                    "preservation_group",
                    "fleet_support_vehicle",
                    "vor",
                    "awaiting_delivery",
                    "trainer_vehicle",
                    "demonstrator",
                    "locked",
                )
            },
        ),
        (
            "Fleet Information",
            {
                "fields": (
                    "joined_fleet",
                    "left_fleet",
                    "previous_operators",
                    "year_of_manufacture",
                    "garage",
                )
            },
        ),
        (
            "Advanced",
            {
                "fields": (
                    "engine",
                    "gearbox",
                    "length",
                    "capacity",
                    "emissions_rating",
                    "chassis",
                    "advanced",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Historical",
            {
                "fields": (
                    "historical_fleet",
                    "historical_fleet_year",
                    "historical_fleet_creator",
                )
            },
        ),
        (
            "Other",
            {
                "fields": (
                    "data",
                    "source",
                    "latest_journey",
                    "latest_journey_data",
                )
            },
        ),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "mass-import/",
                self.admin_site.admin_view(self.mass_import_view),
                name="vehicles_vehicle_mass_import",
            ),
        ]
        return custom_urls + urls

    def save_model(self, request, obj, form, change):
        if request.user.is_superuser:
            obj.is_manual = True
            obj.manual_updated_at = timezone.now()
        super().save_model(request, obj, form, change)

    def _bulk_vehicle_update(
        self,
        request,
        queryset,
        form_class,
        *,
        title,
        submit_label,
        apply_handler,
    ):
        selected = request.POST.getlist(ACTION_CHECKBOX_NAME)
        if "apply" in request.POST:
            form = form_class(request.POST)
            if form.is_valid():
                response = apply_handler(form, queryset)
                if response is None:
                    return None
        else:
            form = form_class()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "queryset": queryset.order_by("operator__name", "fleet_number", "fleet_code", "reg", "code"),
            "form": form,
            "title": title,
            "submit_label": submit_label,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
            "selected": selected,
            "action_name": request.POST.get("action", ""),
        }
        return TemplateResponse(
            request,
            "admin/vehicles/vehicle/bulk_assign.html",
            context,
        )

    def mass_import_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied

        rows = []
        livery_mapping_rows = []
        created = 0
        updated = 0
        errors = 0

        if request.method == "POST":
            form = FleetImportForm(request.POST, request.FILES)
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
                    rows = parse_mass_rows(
                        default_operator,
                        rows_text,
                        default_historical_fleet=historical_fleet,
                        default_historical_year=historical_year,
                    )
                    livery_mapping_rows = build_livery_mapping_rows(
                        rows,
                        manual_livery_selection=manual_livery_selection,
                    )
                    livery_mappings = collect_livery_mappings(request.POST, livery_mapping_rows)
                    for item in livery_mapping_rows:
                        item["selected_livery_id"] = livery_mappings.get(
                            item["raw_name"],
                            item["selected_livery_id"],
                        )

                    form = FleetImportForm(
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
                            rows,
                            livery_mappings=livery_mappings,
                            default_historical_fleet=historical_fleet,
                            default_historical_year=historical_year,
                        )
                        if created or updated:
                            self.message_user(
                                request,
                                f"Mass import complete: created {created}, updated {updated}, errors {errors}",
                                level=messages.SUCCESS,
                            )
                        elif errors:
                            self.message_user(
                                request,
                                f"No rows imported. {errors} row(s) had errors.",
                                level=messages.WARNING,
                            )
        else:
            form = FleetImportForm()

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Mass import vehicles",
            "form": form,
            "rows": rows,
            "livery_mapping_rows": livery_mapping_rows,
            "liveries": models.Livery.objects.order_by("name"),
            "can_commit": any(not row["errors"] for row in rows),
            "created": created,
            "updated": updated,
            "errors": errors,
        }
        return TemplateResponse(
            request,
            "admin/vehicles/vehicle/mass_import.html",
            context,
        )

    def copy_livery(self, request, queryset):
        livery = models.Livery.objects.filter(vehicle__in=queryset).first()
        count = queryset.update(livery=livery)
        self.message_user(request, f"Copied {livery} to {count} vehicles.")

    def copy_type(self, request, queryset):
        vehicle_type = models.VehicleType.objects.filter(vehicle__in=queryset).first()
        count = queryset.update(vehicle_type=vehicle_type)
        self.message_user(request, f"Copied {vehicle_type} to {count} vehicles.")

    def make_livery(self, request, queryset):
        vehicle = queryset.first()
        if vehicle.colours and vehicle.branding:
            livery = models.Livery.objects.create(
                name=vehicle.branding, colours=vehicle.colours, published=True
            )
            vehicles = models.Vehicle.objects.filter(
                colours=vehicle.colours, branding=vehicle.branding
            )
            count = vehicles.update(colours="", branding="", livery=livery)
            self.message_user(request, f"Updated {count} vehicles.")
        else:
            self.message_user(request, "Select a vehicle with colours and branding.")

    @admin.action(description="Mass change livery")
    def mass_change_livery(self, request, queryset):
        def apply_handler(form, selected_queryset):
            livery = form.cleaned_data["livery"]
            updated = selected_queryset.update(
                livery=livery,
                is_manual=True,
                manual_updated_at=timezone.now(),
            )
            label = livery or "no livery"
            self.message_user(
                request,
                f"Updated {updated} vehicle{'s' if updated != 1 else ''} to {label}.",
                level=messages.SUCCESS,
            )
            return None

        return self._bulk_vehicle_update(
            request,
            queryset,
            VehicleBulkAssignLiveryForm,
            title="Mass change livery",
            submit_label="Apply livery",
            apply_handler=apply_handler,
        )

    @admin.action(description="Mass change branding")
    def mass_change_branding(self, request, queryset):
        def apply_handler(form, selected_queryset):
            branding = form.cleaned_data["branding"].strip()
            updated = selected_queryset.update(
                branding=branding,
                is_manual=True,
                manual_updated_at=timezone.now(),
            )
            label = branding or "blank branding"
            self.message_user(
                request,
                f"Updated {updated} vehicle{'s' if updated != 1 else ''} to {label}.",
                level=messages.SUCCESS,
            )
            return None

        return self._bulk_vehicle_update(
            request,
            queryset,
            VehicleBulkSetBrandingForm,
            title="Mass change branding",
            submit_label="Apply branding",
            apply_handler=apply_handler,
        )

    @admin.action(description="Mass assign features")
    def mass_assign_features(self, request, queryset):
        def apply_handler(form, selected_queryset):
            mode = form.cleaned_data["mode"]
            selected_features = list(form.cleaned_data["features"])
            updated = 0
            timestamp = timezone.now()

            for vehicle in selected_queryset.prefetch_related("features"):
                if mode == VehicleBulkAssignFeaturesForm.Mode.ADD:
                    if selected_features:
                        vehicle.features.add(*selected_features)
                elif mode == VehicleBulkAssignFeaturesForm.Mode.REPLACE:
                    vehicle.features.set(selected_features)
                elif mode == VehicleBulkAssignFeaturesForm.Mode.REMOVE:
                    if selected_features:
                        vehicle.features.remove(*selected_features)
                vehicle.is_manual = True
                vehicle.manual_updated_at = timestamp
                vehicle.save(update_fields=["is_manual", "manual_updated_at"])
                updated += 1

            self.message_user(
                request,
                f"Updated features on {updated} vehicle{'s' if updated != 1 else ''}.",
                level=messages.SUCCESS,
            )
            return None

        return self._bulk_vehicle_update(
            request,
            queryset,
            VehicleBulkAssignFeaturesForm,
            title="Mass assign features",
            submit_label="Apply features",
            apply_handler=apply_handler,
        )

    @admin.action(description="Mass log vehicles for a user")
    def mass_log_vehicles(self, request, queryset):
        def apply_handler(form, selected_queryset):
            user = form.cleaned_data["user"]
            created, skipped = bulk_log_vehicles_for_user(user, selected_queryset)
            self.message_user(
                request,
                f"Created {created} ride log(s) for {user}. Skipped {skipped} already logged vehicle(s).",
                level=messages.SUCCESS,
            )
            return None

        return self._bulk_vehicle_update(
            request,
            queryset,
            VehicleBulkLogUserForm,
            title="Mass log vehicles",
            submit_label="Create ride logs",
            apply_handler=apply_handler,
        )

    @admin.action(description="Mass edit vehicles")
    def mass_edit(self, request, queryset):
        def apply_handler(form, selected_queryset):
            # Build update dict with only fields that were provided
            update_fields = {}
            field_mappings = {
                "fleet_number": "fleet_number",
                "prev_registration": "prev_registration",
                "vehicle_type": "vehicle_type",
                "colours": "colours",
                "livery": "livery",
                "name": "name",
                "branding": "branding",
                "rear_advert": "rear_advert",
                "notes": "notes",
                "withdrawn": "withdrawn",
                "preserved": "preserved",
                "fleet_support_vehicle": "fleet_support_vehicle",
                "vor": "vor",
                "awaiting_delivery": "awaiting_delivery",
                "trainer_vehicle": "trainer_vehicle",
                "demonstrator": "demonstrator",
                "year_of_manufacture": "year_of_manufacture",
                "historical_fleet": "historical_fleet",
                "historical_fleet_year": "historical_fleet_year",
                "historical_fleet_creator": "historical_fleet_creator",
                "locked": "locked",
            }
            
            for form_field, model_field in field_mappings.items():
                value = form.cleaned_data.get(form_field)
                if value is not None and value != "":
                    update_fields[model_field] = value
            
            # Always set manual flags
            update_fields["is_manual"] = True
            update_fields["manual_updated_at"] = timezone.now()
            
            if update_fields:
                updated = selected_queryset.update(**update_fields)
                self.message_user(
                    request,
                    f"Updated {updated} vehicle{'s' if updated != 1 else ''}.",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    "No fields were changed.",
                    level=messages.WARNING,
                )
            return None

        return self._bulk_vehicle_update(
            request,
            queryset,
            VehicleBulkEditForm,
            title="Mass edit vehicles",
            submit_label="Apply changes",
            apply_handler=apply_handler,
        )

    def merge_all_selected(self, request, vehicles):
        vehicle = vehicles[0]

        for duplicate in vehicles[1:]:
            if vehicle.preserved:
                self.message_user(
                    request,
                    f"{vehicle} is preserved; clear preserved before merging/deleting it.",
                    messages.WARNING,
                )
                continue
            if duplicate.preserved:
                self.message_user(
                    request,
                    f"{duplicate} is preserved; clear preserved before merging into it.",
                    messages.WARNING,
                )
                continue
            vehicle.vehiclejourney_set.update(vehicle=duplicate)
            vehicle.vehiclecode_set.update(vehicle=duplicate)
            vehicle.vehiclerevision_set.update(vehicle=duplicate)

            if (
                not duplicate.latest_journey_id
                or vehicle.latest_journey_id
                and vehicle.latest_journey_id > duplicate.latest_journey_id
            ):
                duplicate.code = vehicle.code
                duplicate.latest_journey = vehicle.latest_journey
            vehicle.latest_journey = None
            vehicle.save(update_fields=["latest_journey"])
            duplicate.save(update_fields=["latest_journey"])
            duplicate.fleet_code = vehicle.fleet_code
            duplicate.fleet_number = vehicle.fleet_number
            if duplicate.withdrawn and not vehicle.withdrawn:
                duplicate.withdrawn = False
            try:
                models.VehicleCode.objects.create(
                    vehicle=duplicate, scheme="slug", code=vehicle.slug
                )
            except IntegrityError:
                pass
            vehicle.delete()
            duplicate.save(
                update_fields=["code", "fleet_code", "fleet_number", "reg", "withdrawn"]
            )
            self.message_user(
                request,
                format_html(
                    "{} deleted, merged with <a href='{}'>{}</a>",
                    vehicle,
                    duplicate.get_absolute_url(),
                    duplicate,
                ),
            )

    def deduplicate(self, request, queryset):
        for vehicle in queryset.order_by("id"):
            if not vehicle.reg and not vehicle.fleet_code:
                self.message_user(request, f"{vehicle} has no reg")
                continue
            try:
                if vehicle.reg:
                    duplicate = models.Vehicle.objects.get(
                        id__lt=vehicle.id,
                        operator=vehicle.operator_id,
                        reg__iexact=vehicle.reg,
                        preserved=False,
                    )  # vehicle with lower id number we will keep
                else:
                    duplicate = models.Vehicle.objects.get(
                        id__lt=vehicle.id,
                        operator=vehicle.operator_id,
                        fleet_code__iexact=vehicle.fleet_code,
                        preserved=False,
                    )  # vehicle with lower id number we will keep
            except (
                models.Vehicle.DoesNotExist,
                models.Vehicle.MultipleObjectsReturned,
            ) as e:
                self.message_user(request, f"{vehicle} {e}")
                continue
            self.merge_all_selected(request, (vehicle, duplicate))

    def spare_ticket_machine(self, request, queryset):
        queryset.update(
            reg="",
            fleet_code="",
            fleet_number=None,
            name="",
            colours="",
            livery=None,
            branding="",
            vehicle_type=None,
            notes="Spare ticket machine",
        )

    def lock(self, request, queryset):
        queryset.update(locked=True)
        log_change(request, queryset, ["locked"])

    def unlock(self, request, queryset):
        queryset.update(locked=False)
        log_change(request, queryset, ["locked"])

    def preserve(self, request, queryset):
        count = queryset.update(preserved=True)
        self.message_user(request, f"Marked {count} vehicles as preserved.")
        log_change(request, queryset, ["preserved"])

    def unpreserve(self, request, queryset):
        count = queryset.update(preserved=False)
        self.message_user(request, f"Cleared preserved on {count} vehicles.")
        log_change(request, queryset, ["preserved"])

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj and obj.preserved:
            return False
        return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        if obj.preserved:
            self.message_user(
                request,
                f"{obj} is preserved; clear preserved before deleting it.",
                messages.WARNING,
            )
            return
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        preserved_count = queryset.filter(preserved=True).count()
        if preserved_count:
            self.message_user(
                request,
                f"Skipped {preserved_count} preserved vehicles; clear preserved before deleting them.",
                messages.WARNING,
            )
        super().delete_queryset(request, queryset.filter(preserved=False))

    @admin.display(ordering="latest_journey__datetime")
    def last_seen(self, obj):
        if obj.latest_journey:
            return obj.latest_journey.datetime

    @admin.action(description="Export selected vehicles (Basic format)")
    def export_basic_fleet(self, request, queryset):
        # Group by operator for basic export
        from collections import defaultdict
        operators = defaultdict(list)
        for vehicle in queryset.select_related("operator"):
            if vehicle.operator:
                operators[vehicle.operator].append(vehicle)
        
        if len(operators) == 1:
            # Single operator export
            operator = list(operators.keys())[0]
            vehicles = operators[operator]
            workbook = build_basic_fleet_workbook(operator, vehicles, advanced=False)
            filename = f"{operator.slug}-fleet-basic.xlsx"
        else:
            # Multiple operators - export as basic without operator header
            workbook = build_basic_fleet_workbook(None, queryset, advanced=False)
            filename = "fleet-basic.xlsx"
        
        response = HttpResponse(
            workbook_bytes(workbook),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @admin.action(description="Export selected vehicles (Advanced format)")
    def export_advanced_fleet(self, request, queryset):
        if not request.user.advanced_mode:
            self.message_user(
                request,
                "Advanced mode must be enabled in your user settings to use advanced export.",
                messages.WARNING,
            )
            return
        
        # Group by operator for advanced export
        from collections import defaultdict
        operators = defaultdict(list)
        for vehicle in queryset.select_related("operator"):
            if vehicle.operator:
                operators[vehicle.operator].append(vehicle)
        
        if len(operators) == 1:
            # Single operator export
            operator = list(operators.keys())[0]
            vehicles = operators[operator]
            workbook = build_basic_fleet_workbook(operator, vehicles, advanced=True)
            filename = f"{operator.slug}-fleet-advanced.xlsx"
        else:
            # Multiple operators - export as advanced without operator header
            workbook = build_basic_fleet_workbook(None, queryset, advanced=True)
            filename = "fleet-advanced.xlsx"
        
        response = HttpResponse(
            workbook_bytes(workbook),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def get_changelist_form(self, request, **kwargs):
        kwargs.setdefault("form", VehicleAdminForm)
        return super().get_changelist_form(request, **kwargs)


class DuplicateLiveryFilter(admin.SimpleListFilter):
    title = "duplicate name"
    parameter_name = "duplicate_name"

    def lookups(self, request, model_admin):
        return (
            ("yes", "has duplicate name"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            duplicates = models.Livery.objects.filter(~Q(id=OuterRef("id"))).filter(name__iexact=OuterRef("name"))
            queryset = queryset.filter(Exists(duplicates))
        return queryset


class UserFilter(admin.SimpleListFilter):
    title = "user"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        lookups = {
            "Trusted": "Trusted",
            "Banned": "Banned",
            "None": "None",
        }
        if self.value() and self.value() not in lookups:
            lookups[self.value()] = self.value()
        return lookups.items()

    def queryset(self, request, queryset):
        match self.value():
            case "Trusted":
                return queryset.filter(user__trusted=True)
            case "Banned":
                return queryset.filter(user__trusted=False)
            case "None":
                return queryset.filter(user=None)
            case None:
                return queryset
        return queryset.filter(user=self.value())


@admin.register(models.VehicleJourney)
class VehicleJourneyAdmin(admin.ModelAdmin):
    list_display = (
        "datetime",
        "code",
        "vehicle",
        "operator",
        "route_name",
        "service",
        "destination",
    )
    list_select_related = ("vehicle", "service", "vehicle__operator")
    raw_id_fields = ("vehicle", "service", "source", "trip")
    list_filter = (
        "datetime",
        ("service", admin.EmptyFieldListFilter),
        ("trip", admin.EmptyFieldListFilter),
        "source",
        ("vehicle__operator", admin.RelatedOnlyFieldListFilter),
    )
    show_full_result_count = False
    ordering = ("-id",)

    @admin.display(ordering="vehicle__operator")
    def operator(self, obj):
        return obj.vehicle.operator if obj.vehicle else None

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name and not request.GET:
            # no filter yet - return empty queryset rather than trying to load ALL journeys
            return queryset.none()
        return queryset


@admin.register(models.VehicleReview)
class VehicleReviewAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle",
        user,
        "rating",
        "message_preview",
        "status",
        "report_count",
        "updated_at",
    )
    list_filter = ("status", "rating", "updated_at")
    search_fields = (
        "vehicle__code",
        "vehicle__reg",
        "vehicle__fleet_code",
        "user__username",
        "message",
    )
    raw_id_fields = ("vehicle", "user")
    readonly_fields = ("flagged_terms", "created_at", "updated_at")

    @admin.display(ordering="report_count")
    def report_count(self, obj):
        return getattr(obj, "report_count", obj.reports.count())

    @admin.display(description="Message")
    def message_preview(self, obj):
        if len(obj.message) <= 80:
            return obj.message
        return f"{obj.message[:77]}..."

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            return queryset.annotate(report_count=SubqueryCount("reports"))
        return queryset


@admin.register(models.VehicleReviewReport)
class VehicleReviewReportAdmin(admin.ModelAdmin):
    list_display = ("review", "reporter", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("review__message", "reason", "reporter__username")
    raw_id_fields = ("review", "reporter")


@admin.register(models.ReviewBlockedPhrase)
class ReviewBlockedPhraseAdmin(admin.ModelAdmin):
    list_display = ("phrase", "is_active", "notes", "updated_at")
    list_filter = ("is_active", "updated_at")
    search_fields = ("phrase", "notes")
    readonly_fields = ("normalized_phrase", "created_at", "updated_at")


def extract_dominant_colour_from_css(css):
    """Extract the colour with the highest percentage from a CSS gradient."""
    import re

    if not css:
        return None

    # If it's just a single colour (no gradient), return it
    if not css.startswith("linear-gradient") and not css.startswith("to"):
        # It's a plain colour
        match = re.match(r"^#[0-9a-fA-F]{3,6}$", css.strip())
        if match:
            return css.strip()
        return None

    # Parse linear-gradient
    # Format: linear-gradient(90deg,#ff0000 0%,#00ff00 50%,#0000ff 100%)
    # or: linear-gradient(to top,#ff0000,#00ff00,#0000ff)
    match = re.match(r"linear-gradient\(([^,]+),(.+)\)", css)
    if not match:
        return None

    colours_part = match.group(2)

    # Split by commas to get colour entries
    colour_entries = re.findall(r"(#[0-9a-fA-F]{3,6})(?:\s+(\d+)%)?", colours_part)

    if not colour_entries:
        return None

    # If no percentages are specified (like "to top,#ff0000,#00ff00,#0000ff"),
    # assume equal distribution
    if all(entry[1] == "" for entry in colour_entries):
        # Return the first colour
        return colour_entries[0][0]

    # Calculate the percentage range for each colour
    colour_ranges = []
    for i, (colour, percentage) in enumerate(colour_entries):
        if percentage == "":
            # No percentage specified, calculate based on position
            if i == 0:
                start = 0
            else:
                start = int(colour_entries[i - 1][1]) if colour_entries[i - 1][1] else 0
            if i == len(colour_entries) - 1:
                end = 100
            else:
                end = int(colour_entries[i + 1][1]) if colour_entries[i + 1][1] else 100
        else:
            start = int(percentage)
            if i == len(colour_entries) - 1:
                end = 100
            else:
                next_percentage = colour_entries[i + 1][1]
                end = int(next_percentage) if next_percentage else 100

        colour_ranges.append((colour, end - start))

    # Return the colour with the largest range
    if colour_ranges:
        dominant = max(colour_ranges, key=lambda x: x[1])
        return dominant[0]

    return None


class LiveryAdminForm(ModelForm):
    class Meta:
        widgets = {
            "colours": Textarea,
            "css": Textarea,
            "left_css": Textarea,
            "right_css": Textarea,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "colour" in self.fields:
            self.fields["colour"].required = False

    def clean(self):
        cleaned_data = super().clean()
        colour = cleaned_data.get("colour")
        left_css = cleaned_data.get("left_css")
        right_css = cleaned_data.get("right_css")

        if not colour and (left_css or right_css):
            css = left_css or right_css
            dominant_colour = extract_dominant_colour_from_css(css)
            if dominant_colour:
                cleaned_data["colour"] = dominant_colour

        return cleaned_data


def preview(obj, css):
    if obj.text_colour:
        text_colour = obj.text_colour
    elif obj.white_text:
        text_colour = "#fff"
    else:
        text_colour = "#222"
    if obj.stroke_colour:
        stroke = f"stroke:{obj.stroke_colour};stroke-width:3px;paint-order:stroke"
    else:
        stroke = ""

    return format_html(
        """<svg height="24" width="36" style="line-height:24px;font-size:24px;background:{}">
                <text x="50%" y="80%" fill="{}" text-anchor="middle" style="{}">42</text>
            </svg>""",
        css,
        text_colour,
        stroke,
    )


@admin.register(models.Livery)
class LiveryAdmin(admin.ModelAdmin):
    form = LiveryAdminForm
    search_fields = ["name"]
    actions = ["merge"]
    save_as = True
    list_display = [
        "id",
        "name",
        "vehicles",
        "left",
        "right",
        "blob",
        "published",
        "updated_at",
    ]
    list_filter = [
        DuplicateLiveryFilter,
        "published",
        "show_name",
        "updated_at",
        ("vehicle__operator", admin.RelatedOnlyFieldListFilter),
    ]
    ordering = ["-id"]

    readonly_fields = ["left", "right", "blob", "colour", "updated_at"]
    # specify order:
    fields = [
        "name",
        "livery_type",
        "svg",
        "external_id",
        "show_name",
        "colour",
        "blob",
        "colours",
        "angle",
        "horizontal",
        "text_colour",
        "white_text",
        "stroke_colour",
        "left_css",
        "right_css",
        "left",
        "right",
        "published",
        "updated_at",
    ]

    class Media:
        js = ["js/livery-admin.js"]

    def save_model(self, request, obj, form, change):
        if request.user.is_superuser:
            obj.is_manual = True
            obj.manual_updated_at = timezone.now()
        super().save_model(request, obj, form, change)

    def merge(self, request, queryset):
        queryset = queryset.order_by("id")
        if not all(
            queryset[0].colours == livery.colours
            and queryset[0].left_css == livery.left_css
            and queryset[0].right_css == livery.right_css
            for livery in queryset
        ):
            self.message_user(
                request, "You can only merge liveries that are the same", messages.ERROR
            )
        else:
            for livery in queryset[1:]:
                livery.vehicle_set.update(livery=queryset[0])
                livery.revision_from.update(from_livery=queryset[0])
                livery.revision_to.update(to_livery=queryset[0])
            self.message_user(request, "Merged")

    @admin.display(ordering="right_css")
    def right(self, obj):
        return preview(obj, obj.right_css)

    @admin.display(ordering="left_css")
    def left(self, obj):
        return preview(obj, obj.left_css)

    @admin.display(ordering="colour")
    def blob(self, obj):
        if obj.colour:
            return format_html(
                """<svg width="20" height="20">
                    <circle fill="{}" r="10" cx="10" cy="10"></circle>
                </svg>""",
                obj.colour,
            )

    vehicles = VehicleTypeAdmin.vehicles

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            return queryset.annotate(vehicles=SubqueryCount("vehicle"))
        return queryset


class RevisionChangeFilter(admin.SimpleListFilter):
    title = "changed field"
    parameter_name = "change"

    def lookups(self, request, model_admin):
        return (
            ("changes__reg", "reg"),
            ("changes__name", "name"),
            ("changes__branding", "branding"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value and value.startswith("changes__"):
            return queryset.filter(**{f"{value}__isnull": False})
        return queryset


@admin.register(models.VehicleRevision)
class VehicleRevisionAdmin(admin.ModelAdmin):
    raw_id_fields = [
        "from_operator",
        "to_operator",
        "from_operated_by",
        "to_operated_by",
        "from_livery",
        "to_livery",
        "from_type",
        "to_type",
        "from_garage",
        "to_garage",
        "vehicle",
        "user",
        "approved_by",
    ]

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    list_display = ["created_at", "vehicle", "__str__", user, "message"]
    actions = ["revert"]
    list_filter = [
        RevisionChangeFilter,
        UserFilter,
        ("vehicle__operator", admin.RelatedOnlyFieldListFilter),
    ]
    list_select_related = ["from_operator", "to_operator", "from_garage", "to_garage", "vehicle", "user"]

    def get_queryset(self, request):
        return apply_vehicle_schema_compat(
            super().get_queryset(request),
            prefix="vehicle__",
        )

    def revert(self, request, queryset):
        for revision in apply_vehicle_schema_compat(
            queryset.prefetch_related("vehicle"),
            prefix="vehicle__",
        ):
            for message in revision.revert():
                self.message_user(request, message)


@admin.register(models.VehicleCode)
class VehicleCodeAdmin(admin.ModelAdmin):
    raw_id_fields = ["vehicle"]
    list_display = ["id", "scheme", "code", "vehicle"]
    list_filter = ["scheme"]


@admin.register(models.SiriSubscription)
class SiriSubscriptionAdmin(admin.ModelAdmin):
    readonly_fields = ["uuid", "sample", "status"]

    def status(self, obj):
        return cache.get(obj.get_status_key())


admin.site.register(models.VehicleFeature)
