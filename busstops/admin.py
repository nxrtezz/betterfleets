import csv
import io

from django import forms
from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import transaction
from django.db.models import CharField, Exists, F, OuterRef, Q, Value
from django.db.models.aggregates import StringAgg
from django.db.models.functions import Cast, Now, TruncDate
from django.forms import ModelForm, Textarea
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
import openpyxl
from openpyxl.styles import Font
from sql_util.utils import SubqueryCount

from buses.admin_utils import M2MThroughMixin
from bustimes.admin import log_change
from bustimes.models import Route, RouteLink

from . import models


class FleetListImportForm(forms.Form):
    file = forms.FileField(label="CSV or Excel file (.csv, .xlsx)", required=True)


class AssignToOperatorForm(forms.Form):
    operator = forms.ModelChoiceField(
        queryset=models.Operator.objects.all(),
        required=True,
        label="Operator"
    )


@admin.register(models.AdminArea)
class AdminAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "id", "atco_code", "region_id")
    list_filter = ("region_id",)
    search_fields = ("atco_code",)


class StopCodeInline(admin.TabularInline):
    model = models.StopCode
    raw_id_fields = ("source",)


@admin.register(models.StopPoint)
class StopPointAdmin(GISModelAdmin):
    list_display = (
        "atco_code",
        "naptan_code",
        "locality",
        "admin_area",
        "common_name",
        "modified_at",
        "created_at",
    )
    list_select_related = ("locality", "admin_area")
    list_filter = (
        ("source", admin.RelatedOnlyFieldListFilter),
        "modified_at",
        "created_at",
        "active",
        "stop_type",
        "service__region",
        "admin_area",
    )
    raw_id_fields = (
        "source",
        "parents",
        "stop_area",
        "locality",
        "admin_area",
    )
    search_fields = ("atco_code",)
    ordering = ("atco_code",)
    inlines = (StopCodeInline,)
    show_full_result_count = False
    readonly_fields = ("search_vector",)

    def get_search_results(self, request, queryset, search_term):
        if not search_term:
            return super().get_search_results(request, queryset, search_term)

        query = SearchQuery(search_term, search_type="websearch", config="english")
        rank = SearchRank(F("locality__search_vector"), query)
        query = Q(locality__search_vector=query)
        if " " not in search_term:
            query |= Q(atco_code=search_term)
        queryset = queryset.annotate(rank=rank).filter(query).order_by("-rank")
        return queryset, False


@admin.register(models.StopCode)
class StopCodeAdmin(admin.ModelAdmin):
    list_display = ("stop", "code", "source")
    raw_id_fields = ("stop",)


@admin.register(models.StopArea)
class StopAreaAdmin(GISModelAdmin):
    raw_id_fields = ("admin_area", "parent")
    list_filter = ("stop_area_type",)


class OperatorCodeInline(admin.TabularInline):
    model = models.OperatorCode
    raw_id_fields = ("source",)


class OutOfServiceTrackingCodeInline(admin.TabularInline):
    model = models.OutOfServiceTrackingCode
    extra = 0


class OperatorAdminForm(ModelForm):
    class Meta:
        widgets = {
            "address": Textarea,
            "twitter": Textarea,
        }


class DuplicateOperatorFilter(admin.SimpleListFilter):
    title = "duplicate"
    parameter_name = "duplicate"

    def lookups(self, request, model_admin):
        return ((1, "Yes"),)

    def queryset(self, request, queryset):
        if self.value():
            exists = Exists(
                models.Operator.objects.filter(
                    ~Q(pk=OuterRef("pk")),
                    name=OuterRef("name"),
                )
            )
            queryset = queryset.filter(exists)

        return queryset


@admin.register(models.Operator)
class OperatorAdmin(M2MThroughMixin, admin.ModelAdmin):
    form = OperatorAdminForm
    list_display = (
        "name",
        "slug",
        "operator_codes",
        "noc",
        "vehicle_mode",
        "region_id",
        "services",
        "vehicles",
    )
    list_filter = (
        "modified_at",
        DuplicateOperatorFilter,
        "region",
        "vehicle_mode",
        "payment_methods",
        "group",
    )
    search_fields = ("noc", "name")
    raw_id_fields = ("region", "regions", "siblings", "colour", "source")
    inlines = (OperatorCodeInline, OutOfServiceTrackingCodeInline)
    readonly_fields = ("search_vector", "modified_at")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("licences", "payment_methods")
    actions = ("download_vehicles", "upload_fleet_list")
    change_list_template = "admin/busstops/operator/change_list.html"

    fleet_list_headers = [
        "Operator",
        "Vehicle ID",
        "slug",
        "fleet number",
        "fleet code",
        "registration",
        "vehicle type",
        "livery name",
        "branding",
        "withdrawn",
        "features",
    ]

    fleet_list_columns = {
        "operator": "operator",
        "vehicle id": "vehicle_id",
        "slug": "slug",
        "fleet number": "fleet_number",
        "fleet code": "fleet_code",
        "registration": "reg",
        "vehicle type": "vehicle_type",
        "livery name": "livery",
        "branding": "branding",
        "withdrawn": "withdrawn",
        "features": "features",
    }

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "fleet/",
                self.admin_site.admin_view(self.fleet_list_view),
                name="busstops_operator_fleet",
            ),
        ]
        return custom + urls

    def fleet_list_view(self, request):
        if request.method == "POST":
            if request.POST.get("action") == "export":
                return self.export_fleet_list_csv(request)
            return self.import_fleet_list(request)

        return render(
            request,
            "admin/busstops/operator/fleet_list.html",
            {
                "import_form": FleetListImportForm(),
                "operators": models.Operator.objects.order_by("name"),
                "opts": self.model._meta,
            },
        )

    def fleet_list_vehicles(self, operator_ids):
        from vehicles.models import Vehicle

        vehicles = Vehicle.objects.select_related(
            "operator", "vehicle_type", "livery"
        ).prefetch_related("features")
        if operator_ids:
            vehicles = vehicles.filter(operator_id__in=operator_ids)
        return vehicles.order_by("operator__name", "fleet_number", "id")

    def export_fleet_list_csv(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="fleet_list.csv"'

        writer = csv.writer(response)
        writer.writerow(self.fleet_list_headers)

        for vehicle in self.fleet_list_vehicles(request.POST.getlist("operators")):
            writer.writerow(
                [
                    vehicle.operator.name if vehicle.operator else "",
                    vehicle.id,
                    vehicle.slug or "",
                    vehicle.fleet_number or "",
                    vehicle.fleet_code or "",
                    vehicle.reg or "",
                    vehicle.vehicle_type.name if vehicle.vehicle_type else "",
                    vehicle.livery.name if vehicle.livery else "",
                    vehicle.branding or "",
                    "True" if vehicle.withdrawn else "False",
                    ", ".join(
                        feature.name for feature in vehicle.features.all()
                    ),
                ]
            )
        return response

    def import_fleet_list(self, request):
        from vehicles.models import (
            Livery,
            Vehicle,
            VehicleFeature,
            VehicleType,
        )

        form = FleetListImportForm(request.POST, request.FILES)
        if not form.is_valid():
            return self._fleet_list_response(request, form)

        uploaded = request.FILES["file"]
        rows = []
        try:
            if uploaded.name.lower().endswith((".xlsx", ".xlsm")):
                workbook = openpyxl.load_workbook(uploaded, read_only=True)
                worksheet = workbook.active
                rows_iter = worksheet.iter_rows(values_only=True)
                headers = [str(cell or "").strip().lower() for cell in next(rows_iter)]
                column_map = self._fleet_list_column_map(headers)
                for row in rows_iter:
                    rows.append(
                        {
                            column_map.get(headers[i]): str(cell or "").strip()
                            for i, cell in enumerate(row)
                            if i < len(headers) and column_map.get(headers[i])
                        }
                    )
            else:
                text = uploaded.read().decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                column_map = self._fleet_list_column_map(
                    [key.strip().lower() for key in (reader.fieldnames or [])]
                )
                if not column_map:
                    raise ValueError("No recognised columns in CSV header")
                for raw in reader:
                    rows.append(
                        {
                            column_map[key.strip().lower()]: (value or "").strip()
                            for key, value in raw.items()
                            if key is not None
                            and key.strip().lower() in column_map
                        }
                    )
        except Exception as e:
            self.message_user(request, f"Error reading file: {e}", messages.ERROR)
            return self._fleet_list_response(request, FleetListImportForm())

        updated_count = 0
        created_count = 0
        errors = []

        for row_num, row in enumerate(rows, 2):
            try:
                vehicle = None
                if row.get("vehicle_id"):
                    vehicle = Vehicle.objects.filter(id=row["vehicle_id"]).first()
                    if vehicle is None:
                        errors.append(f"Row {row_num}: Vehicle ID {row['vehicle_id']} not found")
                        continue

                operator = None
                operator_value = row.get("operator", "")
                if operator_value:
                    operator = models.Operator.objects.filter(
                        noc__iexact=operator_value
                    ).first() or models.Operator.objects.filter(
                        name__iexact=operator_value
                    ).first()
                    if operator is None:
                        errors.append(
                            f"Row {row_num}: Operator '{operator_value}' not found"
                        )
                        continue

                vehicle_type = None
                if row.get("vehicle_type"):
                    vehicle_type = VehicleType.objects.filter(
                        name__iexact=row["vehicle_type"]
                    ).first()
                    if vehicle_type is None:
                        errors.append(
                            f"Row {row_num}: Vehicle type '{row['vehicle_type']}' not found"
                        )
                        continue

                livery = None
                if row.get("livery"):
                    livery = Livery.objects.filter(name__iexact=row["livery"]).first()
                    if livery is None:
                        errors.append(
                            f"Row {row_num}: Livery '{row['livery']}' not found"
                        )
                        continue

                if vehicle is None:
                    if operator is None:
                        errors.append(
                            f"Row {row_num}: No operator specified for new vehicle"
                        )
                        continue
                    vehicle = Vehicle(operator=operator)
                    vehicle.code = row.get("slug") or f"import-{row_num}"
                    created_count += 1
                else:
                    updated_count += 1
                    if operator is not None:
                        vehicle.operator = operator

                if "slug" in row and row["slug"]:
                    vehicle.slug = row["slug"]
                if "fleet_number" in row:
                    vehicle.fleet_number = int(row["fleet_number"]) if row["fleet_number"] else None
                if "fleet_code" in row:
                    vehicle.fleet_code = row["fleet_code"]
                if "reg" in row:
                    vehicle.reg = row["reg"]
                if "vehicle_type" in row:
                    vehicle.vehicle_type = vehicle_type
                if "livery" in row:
                    vehicle.livery = livery
                if "branding" in row:
                    vehicle.branding = row["branding"]
                if "withdrawn" in row and row["withdrawn"]:
                    vehicle.withdrawn = row["withdrawn"].lower() in (
                        "true",
                        "1",
                        "yes",
                    )

                vehicle.save()

                if "features" in row:
                    features = [
                        VehicleFeature.objects.get_or_create(name=name)[0]
                        for name in (
                            feature.strip()
                            for feature in row["features"].split(",")
                            if feature.strip()
                        )
                    ]
                    vehicle.features.set(features)
            except Exception as e:
                errors.append(f"Row {row_num}: {e}")

        self.message_user(
            request,
            f"Imported fleet list: {created_count} created, {updated_count} updated",
        )
        if errors:
            self.message_user(
                request,
                f"Errors: {', '.join(errors[:10])}"
                + ("..." if len(errors) > 10 else ""),
                messages.WARNING,
            )
        return self._fleet_list_response(request, FleetListImportForm())

    def _fleet_list_column_map(self, headers):
        return {
            header: self.fleet_list_columns[header]
            for header in headers
            if header in self.fleet_list_columns
        }

    def _fleet_list_response(self, request, form):
        return render(
            request,
            "admin/busstops/operator/fleet_list.html",
            {
                "import_form": form,
                "operators": models.Operator.objects.order_by("name"),
                "opts": self.model._meta,
            },
        )

    def get_exclude(self, request, obj=None):
        if obj:
            return [
                field
                for field in ("twitter", "address", "email", "phone", "qualifier_name")
                if not getattr(obj, field)
            ]

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(
                services=SubqueryCount("service", filter=Q(service__current=True)),
                vehicles=SubqueryCount("vehicle"),
            ).prefetch_related("operatorcode_set")
        return queryset

    @admin.display(ordering="services")
    def services(self, obj):
        url = reverse("admin:busstops_service_changelist")
        return format_html(
            '<a href="{}?operator__noc__exact={}">{}</a>', url, obj.noc, obj.services
        )

    @admin.display(ordering="vehicles")
    def vehicles(self, obj):
        url = reverse("admin:vehicles_vehicle_changelist")
        return format_html(
            '<a href="{}?operator__noc__exact={}">{}</a>', url, obj.noc, obj.vehicles
        )

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )

        if request.path.endswith("/autocomplete/"):
            queryset = queryset.filter(
                Q(noc=search_term)
                | Exists(
                    models.Service.objects.filter(operator=OuterRef("pk"), current=True)
                )
            )

        return queryset, use_distinct

    @staticmethod
    def payment(obj):
        return ", ".join(str(code) for code in obj.payment_methods.all())

    @staticmethod
    def operator_codes(obj):
        return ", ".join(str(code) for code in obj.operatorcode_set.all())


class ServiceCodeInline(admin.TabularInline):
    model = models.ServiceCode


class RouteInline(admin.TabularInline):
    model = Route
    show_change_link = True
    fields = ("source", "code", "service_code")
    raw_id_fields = ("source",)


class FromServiceLinkInline(admin.TabularInline):
    model = models.ServiceLink
    fk_name = "from_service"
    autocomplete_fields = ("to_service",)


class ToServiceLinkInline(FromServiceLinkInline):
    fk_name = "to_service"
    autocomplete_fields = ("from_service",)


class SplitServiceFilter(DuplicateOperatorFilter):
    title = "split"
    parameter_name = "split"

    def queryset(self, request, queryset):
        if self.value():
            exists = Exists(
                Route.objects.filter(
                    Exists(
                        Route.objects.filter(
                            ~Q(service=OuterRef("service")),
                            source=OuterRef("source"),
                            service_code=OuterRef("service_code"),
                        )
                    ),
                    ~Q(service_code=""),
                    service=OuterRef("id"),
                )
            )
            queryset = queryset.filter(exists)

        return queryset


class DuplicateLineNameFilter(DuplicateOperatorFilter):
    title = "duplicate line name"
    parameter_name = "duplicate_line_name"

    def queryset(self, request, queryset):
        if self.value():
            exists = Exists(
                models.Service.objects.filter(
                    ~Q(id=OuterRef("id")),
                    line_name__iexact=OuterRef("line_name"),
                    source=OuterRef("source"),
                    # current=True,
                )
            )
            queryset = queryset.filter(exists)

        return queryset


class HasCurrentRouteFilter(admin.SimpleListFilter):
    title = "has current route"
    parameter_name = "has_current_route"

    def lookups(self, request, model_admin):
        return (
            ("1", "Yes"),
            ("0", "No"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            today = TruncDate(Now())

            superseded = Exists(
                Route.objects.filter(
                    service=OuterRef("service"),
                    source=OuterRef("source"),
                    service_code=OuterRef("service_code"),
                    revision_number_context=OuterRef("revision_number_context"),
                    revision_number__gt=OuterRef("revision_number"),
                    start_date__lte=today,
                )
            )
            exists = Exists(
                Route.objects.filter(
                    Q(end_date=None) | Q(end_date__gte=today),
                    ~superseded,
                    service=OuterRef("id"),
                )
            )
            if value == "1":
                queryset = queryset.filter(exists)
            elif value == "0":
                queryset = queryset.filter(~exists)

        return queryset


@admin.register(models.Service)
class ServiceAdmin(M2MThroughMixin, GISModelAdmin):
    list_display = (
        "id",
        "line_name",
        "description",
        "service_codes",
        "mode",
        "region_id",
        "routes",
        "current",
        "timetable_wrong",
        "public_use",
        "colour",
        "line_brand",
        "modified_at",
    )
    list_filter = (
        SplitServiceFilter,
        DuplicateLineNameFilter,
        HasCurrentRouteFilter,
        "current",
        "timetable_wrong",
        "public_use",
        "tracking",
        "trip_chaining",
        "mode",
        "region",
        ("source", admin.RelatedOnlyFieldListFilter),
        ("operator", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("service_code", "line_name", "line_brand", "description")
    raw_id_fields = ("operator", "stops", "colour", "source")
    inlines = (
        ServiceCodeInline,
        RouteInline,
        FromServiceLinkInline,
        ToServiceLinkInline,
    )
    readonly_fields = ("search_vector", "modified_at")
    list_editable = ("colour", "line_brand")
    list_select_related = ("colour",)
    actions = ("current_false", "current_true", "public_use_true", "merge", "unmerge", "assign_garage", "assign_to_operator")

    def lookup_allowed(self, lookup, value, request):
        if lookup == "route__source__source":
            return True
        return super().lookup_allowed(lookup, value, request)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        match db_field.name:
            case "public_use":
                kwargs["help_text"] = mark_safe(
                    "set this to Yes to override an errant "
                    "&lt;PublicUse&gt;false&lt;/PublicUse&gt; in the TransXChange file"
                )
            case "current":
                kwargs["help_text"] = "untick to (effectively) delete, tick to undelete"
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    @admin.display(ordering="routes")
    def routes(self, obj):
        return obj.routes

    @admin.display(ordering="service_codes")
    def service_codes(self, obj):
        return obj.service_codes

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(routes=SubqueryCount("route"))

            queryset = queryset.annotate(
                service_codes=StringAgg("route__service_code", Value(" "))
            )

        return queryset

    def get_search_results(self, request, queryset, search_term):
        if search_term and request.path.endswith("/autocomplete/"):
            queryset = queryset.filter(current=True)

            query = SearchQuery(search_term, search_type="websearch", config="english")
            rank = SearchRank(F("search_vector"), query)
            queryset = (
                queryset.annotate(rank=rank)
                .filter(Q(search_vector=query) | Q(service_code=search_term))
                .order_by("-rank")
            )
            return queryset, False

        return super().get_search_results(request, queryset, search_term)

    def current_false(self, request, queryset):
        result = queryset.order_by().update(current=False, modified_at=Now())
        log_change(request, queryset, ["current"])
        self.message_user(request, f"{result}")

    def current_true(self, request, queryset):
        result = queryset.order_by().update(current=True, modified_at=Now())
        log_change(request, queryset, ["current"])
        self.message_user(request, f"{result}")

    def public_use_true(self, request, queryset):
        result = queryset.order_by().update(public_use=True, modified_at=Now())
        log_change(request, queryset, ["public_use"])
        self.message_user(request, f"{result}")

    @transaction.atomic
    def merge(self, request, queryset):
        first = queryset[0]
        others = queryset[1:]

        first.current = True

        for other in others:
            if other.current:
                other.route_set.update(service=first)
                first.operator.add(*other.operator.all())
            else:
                # route.service is no longer ON DELETE CASCADE
                other.route_set.all().delete()
            other.vehiclejourney_set.update(service=first)
            other.servicecode_set.filter(
                ~Exists(
                    models.ServiceCode.objects.filter(
                        scheme=OuterRef("scheme"), code=OuterRef("code"), service=first
                    )
                )
            ).update(service=first)

            other.routelink_set.filter(
                ~Exists(
                    RouteLink.objects.filter(
                        from_stop=OuterRef("from_stop"),
                        to_stop=OuterRef("to_stop"),
                        service=first,
                    )
                )
            ).update(service=first)

            if not first.servicecode_set.filter(
                code=other.slug, scheme="slug"
            ).exists():
                models.ServiceCode.objects.create(
                    code=other.slug, service=first, scheme="slug"
                )

            if (
                other.service_code
                and other.service_code != first.service_code
                and not first.servicecode_set.filter(
                    code=other.service_code, scheme="ServiceCode"
                ).exists()
            ):
                models.ServiceCode.objects.create(
                    code=other.service_code, service=first, scheme="ServiceCode"
                )

            other.delete()

        first.do_stop_usages()
        first.update_geometry()
        first.save(force_update=True)

        first.update_description()
        first.update_search_vector()

        self.message_user(request, f"merged {others} into {first}")

    def unmerge(self, request, queryset):
        for service in queryset:
            with transaction.atomic():
                services_by_line_name = {service.line_name: service.id}
                service_id = service.id  # for use later
                operators = service.operator.all()
                routes = service.route_set.all()
                journeys = service.vehiclejourney_set.all()
                bool(journeys)  # force evaluation
                service_codes = service.servicecode_set.all()
                bool(service_codes)  # force evaluation
                for route in routes:
                    if route.line_name not in services_by_line_name:
                        service.id = None
                        service.line_name = route.line_name
                        service.description = route.description
                        service.search_vector = None
                        service.slug = ""
                        service.save(force_insert=True)
                        service.operator.set(operators)
                        services_by_line_name[route.line_name] = service.id
                    route.service_id = services_by_line_name[route.line_name]
                    route.save(update_fields=["service_id"])

                for service in models.Service.objects.filter(
                    id__in=services_by_line_name.values()
                ):
                    service.do_stop_usages()
                    service.update_geometry()
                    service.update_search_vector()
                    if service.id != service_id:
                        journeys.filter(
                            Q(trip__route__service=service)
                            | Q(route_name__iexact=service.line_name)
                        ).update(service=service)
                        service_codes.filter(
                            code__istartswith=f"{service.line_name}-"
                        ).update(service=service)

    def assign_garage(self, request, queryset):
        from bustimes.models import Garage

        count = 0
        for service in queryset:
            operators = service.operator.all()
            if operators:
                garage = Garage.objects.filter(operator=operators.first()).first()
                if garage:
                    service.garage = garage
                    service.save(update_fields=["garage"])
                    count += 1
        self.message_user(request, f"Assigned garage to {count} services.")

    def assign_to_operator(self, request, queryset):
        if request.method == "POST" and "apply" in request.POST:
            form = AssignToOperatorForm(request.POST)
            if form.is_valid():
                operator = form.cleaned_data["operator"]
                count = 0
                for service in queryset:
                    service.operator.add(operator)
                    count += 1
                self.message_user(request, f"Assigned {count} services to {operator}")
                return HttpResponseRedirect(
                    reverse("admin:busstops_service_changelist")
                )
        else:
            form = AssignToOperatorForm()

        context = {
            "form": form,
            "queryset": queryset,
            "action_checkbox_name": "_selected_action",
            "opts": self.model._meta,
            "action": "assign_to_operator",
        }
        return render(request, "admin/assign_to_operator.html", context)

    assign_to_operator.short_description = "Assign to operator"

    def download_vehicles(self, request, queryset):
        from vehicles.models import Vehicle

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="vehicles.xlsx"'

        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        worksheet.title = "Vehicles"

        # Header row
        headers = [
            "Vehicle ID",
            "Operator (noc)",
            "slug",
            "code",
            "fleet number",
            "reg",
            "vehicle type",
            "livery id",
            "branding",
            "name",
            "garage",
        ]
        for col_num, header in enumerate(headers, 1):
            cell = worksheet.cell(row=1, column=col_num, value=header)
            cell.font = Font(bold=True)

        # Get all vehicles for the selected operators
        vehicles = Vehicle.objects.filter(operator__in=queryset).select_related(
            "operator", "vehicle_type", "livery", "garage"
        )

        for row_num, vehicle in enumerate(vehicles, 2):
            worksheet.cell(row=row_num, column=1, value=vehicle.id)
            worksheet.cell(row=row_num, column=2, value=vehicle.operator.noc if vehicle.operator else "")
            worksheet.cell(row=row_num, column=3, value=vehicle.slug or "")
            worksheet.cell(row=row_num, column=4, value=vehicle.code or "")
            worksheet.cell(row=row_num, column=5, value=vehicle.fleet_number or "")
            worksheet.cell(row=row_num, column=6, value=vehicle.reg or "")
            worksheet.cell(row=row_num, column=7, value=vehicle.vehicle_type.name if vehicle.vehicle_type else "")
            worksheet.cell(row=row_num, column=8, value=vehicle.livery_id or "")
            worksheet.cell(row=row_num, column=9, value=vehicle.branding or "")
            worksheet.cell(row=row_num, column=10, value=vehicle.name or "")
            worksheet.cell(row=row_num, column=11, value=vehicle.garage_id or "")

        workbook.save(response)
        return response

    download_vehicles.short_description = "Download vehicle list as Excel"

    def upload_fleet_list(self, request, queryset):
        if request.method == "POST" and "apply" in request.POST:
            from vehicles.admin import VehicleUploadForm

            form = VehicleUploadForm(request.POST, request.FILES)
            if form.is_valid():
                file = request.FILES["file"]
                include_withdrawn = form.cleaned_data["include_withdrawn"]
                replace_mode = form.cleaned_data["replace_mode"]

                try:
                    workbook = openpyxl.load_workbook(file)
                    worksheet = workbook.active

                    if worksheet.max_row < 2:
                        self.message_user(request, "File is empty", messages.ERROR)
                        return HttpResponseRedirect(
                            reverse("admin:busstops_operator_changelist")
                        )

                    # Verify header row
                    headers = [
                        worksheet.cell(row=1, column=col).value
                        for col in range(1, 12)
                    ]
                    expected_headers = [
                        "Vehicle ID",
                        "Operator (noc)",
                        "slug",
                        "code",
                        "fleet number",
                        "reg",
                        "vehicle type",
                        "livery id",
                        "branding",
                        "name",
                        "garage",
                    ]
                    if headers != expected_headers:
                        self.message_user(
                            request,
                            f"Invalid headers. Expected: {expected_headers}",
                            messages.ERROR,
                        )
                        return HttpResponseRedirect(
                            reverse("admin:busstops_operator_changelist")
                        )

                    from bustimes.models import Garage
                    from vehicles.models import Vehicle, VehicleType, Livery

                    updated_count = 0
                    created_count = 0
                    deleted_count = 0
                    errors = []

                    # Get vehicle IDs from the file for replace mode
                    file_vehicle_ids = set()

                    for row_num in range(2, worksheet.max_row + 1):
                        vehicle_id = worksheet.cell(row=row_num, column=1).value
                        operator_noc = worksheet.cell(row=row_num, column=2).value
                        slug = worksheet.cell(row=row_num, column=3).value
                        code = worksheet.cell(row=row_num, column=4).value
                        fleet_number = worksheet.cell(row=row_num, column=5).value
                        reg = worksheet.cell(row=row_num, column=6).value
                        vehicle_type_name = worksheet.cell(row=row_num, column=7).value
                        livery_id = worksheet.cell(row=row_num, column=8).value
                        branding = worksheet.cell(row=row_num, column=9).value
                        name = worksheet.cell(row=row_num, column=10).value
                        garage_id = worksheet.cell(row=row_num, column=11).value

                        file_vehicle_ids.add(vehicle_id)

                        try:
                            # Get operator
                            operator = None
                            if operator_noc:
                                operator = models.Operator.objects.filter(noc=operator_noc).first()

                            # Skip if operator not in selected queryset
                            if operator and operator not in queryset:
                                continue

                            # Get vehicle type
                            vehicle_type = None
                            if vehicle_type_name:
                                vehicle_type = VehicleType.objects.filter(
                                    name=vehicle_type_name
                                ).first()

                            # Get livery
                            livery = None
                            if livery_id:
                                livery = Livery.objects.filter(id=livery_id).first()

                            # Get garage
                            garage = None
                            if garage_id:
                                garage = Garage.objects.filter(id=garage_id).first()

                            if vehicle_id:
                                # Update existing vehicle
                                vehicle = Vehicle.objects.filter(id=vehicle_id).first()
                                if vehicle:
                                    if operator:
                                        vehicle.operator = operator
                                    if slug:
                                        vehicle.slug = slug
                                    if code:
                                        vehicle.code = code
                                    if fleet_number:
                                        vehicle.fleet_number = fleet_number
                                    if reg:
                                        vehicle.reg = reg
                                    if vehicle_type:
                                        vehicle.vehicle_type = vehicle_type
                                    if livery_id is not None:
                                        vehicle.livery = livery
                                    if branding:
                                        vehicle.branding = branding
                                    if name:
                                        vehicle.name = name
                                    if garage_id is not None:
                                        vehicle.garage = garage

                                    vehicle.save()
                                    updated_count += 1
                                else:
                                    errors.append(f"Vehicle ID {vehicle_id} not found")
                            else:
                                # Create new vehicle
                                if not operator:
                                    errors.append(f"Row {row_num}: No operator specified for new vehicle")
                                    continue

                                vehicle = Vehicle.objects.create(
                                    operator=operator,
                                    slug=slug or "",
                                    code=code or "",
                                    fleet_number=fleet_number,
                                    reg=reg or "",
                                    vehicle_type=vehicle_type,
                                    livery=livery,
                                    branding=branding or "",
                                    name=name or "",
                                    garage=garage,
                                )
                                created_count += 1

                        except Exception as e:
                            errors.append(f"Row {row_num}: {str(e)}")

                    # Replace mode: delete vehicles not in the file
                    if replace_mode:
                        operator_ids = [op.id for op in queryset]
                        vehicles_to_delete = Vehicle.objects.filter(
                            operator__id__in=operator_ids
                        ).exclude(id__in=file_vehicle_ids)

                        if not include_withdrawn:
                            vehicles_to_delete = vehicles_to_delete.filter(withdrawn=False)

                        deleted_count = vehicles_to_delete.count()
                        vehicles_to_delete.delete()

                    self.message_user(
                        request,
                        f"Updated {updated_count}, created {created_count}, deleted {deleted_count} vehicles",
                    )
                    if errors:
                        self.message_user(
                            request,
                            f"Errors: {', '.join(errors[:10])}" + ("..." if len(errors) > 10 else ""),
                            messages.WARNING,
                        )

                    return HttpResponseRedirect(
                        reverse("admin:busstops_operator_changelist")
                    )

                except Exception as e:
                    self.message_user(request, f"Error processing file: {str(e)}", messages.ERROR)
                    return HttpResponseRedirect(
                        reverse("admin:busstops_operator_changelist")
                    )
        else:
            from vehicles.admin import VehicleUploadForm
            form = VehicleUploadForm()

        context = {
            "form": form,
            "queryset": queryset,
            "action_checkbox_name": "_selected_action",
            "opts": self.model._meta,
            "action": "upload_fleet_list",
        }
        return render(request, "vehicles/admin/upload_fleet_list.html", context)

    upload_fleet_list.short_description = "Upload fleet list from Excel"


@admin.register(models.ServiceLink)
class ServiceLinkAdmin(admin.ModelAdmin):
    save_as = True
    list_display = (
        "from_service",
        "from_service__current",
        "to_service",
        "to_service__current",
        "how",
    )
    list_filter = (
        "from_service__current",
        "to_service__current",
        "from_service__source",
        "to_service__source",
    )
    autocomplete_fields = ("from_service", "to_service")

    @staticmethod
    def from_service__current(obj):
        return obj.from_service.current

    @staticmethod
    def to_service__current(obj):
        return obj.to_service.current


@admin.register(models.Locality)
class LocalityAdmin(GISModelAdmin):
    list_display = ("id", "name", "slug", "modified_at", "created_at")
    search_fields = ("id", "name")
    raw_id_fields = ("adjacent", "parent")
    list_filter = ("modified_at", "created_at", "admin_area__region", "admin_area")
    readonly_fields = ("search_vector",)


@admin.register(models.OperatorCode)
class OperatorCodeAdmin(admin.ModelAdmin):
    save_as = True
    list_display = ("id", "operator", "source", "code")
    list_filter = (("source", admin.RelatedOnlyFieldListFilter),)
    search_fields = ("code",)
    raw_id_fields = ("operator",)


@admin.register(models.ServiceCode)
class ServiceCodeAdmin(admin.ModelAdmin):
    list_display = ("id", "service", "scheme", "code")
    list_filter = (
        "scheme",
        "service__current",
        ("service__operator", admin.RelatedOnlyFieldListFilter),
        "service__stops__admin_area",
    )
    search_fields = ("code", "service__line_name", "service__description")
    autocomplete_fields = ("service",)


@admin.register(models.Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "url")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(models.ServiceColour)
class ServiceColourAdmin(admin.ModelAdmin):
    list_display = ("preview", "foreground", "background", "services")
    search_fields = ("name",)
    list_filter = (("service__operator", admin.EmptyFieldListFilter),)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(
                services=SubqueryCount("service", filter=Q(current=True))
            )
        return queryset

    @admin.display(ordering="services")
    def services(self, obj):
        return obj.services


@admin.register(models.DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    search_fields = ("name", "url")
    list_display = (
        "name",
        "description",
        "url",
        "sha1",
        "datetime",
        "settings",
        "routes",
        "services",
        "source",
        # "journeys",
    )
    list_filter = (
        ("route", admin.EmptyFieldListFilter),
        ("service", admin.EmptyFieldListFilter),
        ("vehiclejourney", admin.EmptyFieldListFilter),
    )
    actions = ("delete_routes", "remove_datetimes")
    show_full_result_count = False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(
                routes=SubqueryCount("route", filter=~Q(service=None)),
                services=SubqueryCount("service", filter=Q(current=True)),
                # journeys=Exists(VehicleJourney.objects.filter(source=OuterRef("id"))),
            ).prefetch_related("operatorcode_set")
        return queryset

    @admin.display(ordering="routes")
    def routes(self, obj):
        url = reverse("admin:bustimes_route_changelist")
        return format_html(
            '<a href="{}?source__id__exact={}">{}</a>', url, obj.id, obj.routes
        )

    @admin.display(ordering="services")
    def services(self, obj):
        url = reverse("admin:busstops_service_changelist")
        return format_html(
            '<a href="{}?source__id__exact={}">{}</a>', url, obj.id, obj.services
        )

    def delete_routes(self, request, queryset):
        result = Route.objects.filter(source__in=queryset).update(service=None)
        self.message_user(request, result)

    def remove_datetimes(self, request, queryset):
        result = queryset.order_by().update(datetime=None, sha1="")
        log_change(request, queryset, ["datetime", "sha1"])
        self.message_user(request, result)


@admin.register(models.SIRISource)
class SIRISourceAdmin(M2MThroughMixin, admin.ModelAdmin):
    list_display = ("name", "url", "requestor_ref", "areas", "is_poorly")
    autocomplete_fields = ("operators", "admin_areas")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(
                areas=StringAgg(
                    Cast("admin_areas__atco_code", output_field=CharField()),
                    Value(", "),
                )
            )
        return queryset

    @staticmethod
    def areas(obj):
        return obj.areas


class PaymentMethodOperatorInline(admin.TabularInline):
    model = models.PaymentMethod.operator_set.through
    autocomplete_fields = ("operator",)


class PaymentMethodServiceInline(admin.TabularInline):
    model = models.PaymentMethod.service_set.through
    autocomplete_fields = ("service",)


@admin.register(models.PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "url", "operators")
    inlines = (PaymentMethodOperatorInline, PaymentMethodServiceInline)
    search_fields = ("name",)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if "changelist" in request.resolver_match.view_name:
            queryset = queryset.annotate(
                operators=StringAgg("operator", Value(", "), distinct=True)
            )
        return queryset

    @staticmethod
    def operators(obj):
        return obj.operators


admin.site.register(models.Region)
admin.site.register(models.District)
admin.site.register(models.OperatorGroup)
