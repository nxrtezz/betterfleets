from io import BytesIO
import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from busstops.models import Operator

from .forms import LiveFleetBulkImportForm
from .historical_fleet_bulk_import import (
    build_template_workbook,
    bulk_import_live_vehicles,
    export_operator_fleet_rows,
    rows_text_from_uploaded_workbook,
)
from .models import Vehicle, VehicleType, Livery


# AdditionRequest model was removed - these configurations and views are no longer functional
# REQUEST_CONFIGS = {
#     AdditionRequestType.LIVERY: {
#         "title": "Request a livery",
#         "intro": "Submit a livery for review. A superuser has to approve it before it becomes selectable in fleet imports and edits.",
#         "form_class": LiveryRequestForm,
#         "nav_label": "Liveries",
#     },
#     AdditionRequestType.VEHICLE_TYPE: {
#         "title": "Request a vehicle type",
#         "intro": "Submit a vehicle type for review. Superusers approve these before they become available in the fleet database.",
#         "form_class": VehicleTypeRequestForm,
#         "nav_label": "Vehicle Types",
#     },
#     AdditionRequestType.VEHICLE: {
#         "title": "Request a vehicle",
#         "intro": "Submit a specific vehicle for review. Include all details like fleet number, registration, operator, livery, and other specifications.",
#         "form_class": VehicleRequestForm,
#         "nav_label": "Vehicles",
#     },
#     AdditionRequestType.OPERATOR: {
#         "title": "Request an operator",
#         "intro": "Submit a new operator for review. Only superusers can authorise the operator into the live database.",
#         "form_class": OperatorRequestForm,
#         "nav_label": "Operators",
#     },
#     AdditionRequestType.GARAGE: {
#         "title": "Request a garage",
#         "intro": "Submit a garage for review. Superusers approve these before they can be assigned to vehicles.",
#         "form_class": GarageRequestForm,
#         "nav_label": "Garage",
#     },
# }
#
#
# REQUEST_TYPE_ALIASES = {
#     "liveries": AdditionRequestType.LIVERY,
#     "vehicle-types": AdditionRequestType.VEHICLE_TYPE,
#     "vehicles": AdditionRequestType.VEHICLE,
#     "operators": AdditionRequestType.OPERATOR,
#     "garages": AdditionRequestType.GARAGE,
# }
#
#
# REQUEST_NAV = [
#     (AdditionRequestType.LIVERY, "/requests/liveries"),
#     (AdditionRequestType.VEHICLE_TYPE, "/requests/vehicle-types"),
#     (AdditionRequestType.VEHICLE, "/requests/vehicles"),
#     (AdditionRequestType.OPERATOR, "/requests/operators"),
#     (AdditionRequestType.GARAGE, "/requests/garages"),
# ]


def _ensure_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _build_workbook_response(workbook, filename: str):
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    response = HttpResponse(
        stream.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# AdditionRequest model was removed - these views are no longer functional
# @login_required
# def request_hub(request):
#     recent_requests = []
#     pending_requests = None
#
#     # Use safe manager methods to handle encoding errors
#     recent_requests = (
#         AdditionRequest.objects.safe_filter(requested_by=request.user)
#         .select_related("reviewed_by")
#         .order_by("status", "-created_at")[:20]
#     )
#
#     pending_requests = None
#     if request.user.is_superuser:
#         pending_requests = AdditionRequest.objects.safe_filter(
#             status=AdditionRequestStatus.PENDING
#         ).select_related("requested_by")[:20]
#
#     return render(
#         request,
#         "requests/request_hub.html",
#         {
#             "request_nav": REQUEST_NAV,
#             "recent_requests": recent_requests,
#             "pending_requests": pending_requests,
#         },
#     )
#
#
# @login_required
# def addition_request_page(request, request_type):
#     request_type = REQUEST_TYPE_ALIASES.get(request_type, request_type)
#     config = REQUEST_CONFIGS[request_type]
#     form_class = config["form_class"]
#     form = form_class(request.POST or None)
#     if request.method == "POST" and form.is_valid():
#         form.save(request.user)
#         messages.success(
#             request,
#             f"{config['nav_label']} request submitted for approval.",
#         )
#         return redirect(request.path)
#
#     recent_requests = (
#         AdditionRequest.objects.filter(requested_by=request.user, request_type=request_type)
#         .select_related("reviewed_by")
#         .order_by("-created_at")[:10]
#     )
#     return render(
#         request,
#         "requests/request_form.html",
#         {
#             "form": form,
#             "request_type": request_type,
#             "request_nav": REQUEST_NAV,
#             "page_title": config["title"],
#             "page_intro": config["intro"],
#             "recent_requests": recent_requests,
#         },
#     )
#
#
# @login_required
# def addition_request_review(request):
#     _ensure_superuser(request)
#
#     try:
#         if request.method == "POST":
#             action = request.POST.get("action")
#             try:
#                 with transaction.atomic():
#                     addition_request = get_object_or_404(
#                         AdditionRequest.objects.select_for_update(),
#                         pk=request.POST.get("request_id"),
#                     )
#                     if action == "approve":
#                         created_object = addition_request.approve(request.user)
#                         messages.success(
#                             request,
#                             f"Approved {addition_request.get_summary()} and created {created_object}.",
#                         )
#                     elif action == "reject":
#                         addition_request.reject(
#                             request.user,
#                             notes=(request.POST.get("review_notes") or "").strip(),
#                         )
#                         messages.success(
#                             request,
#                             f"Rejected {addition_request.get_summary()}.",
#                         )
#             except ValueError as exc:
#                 messages.error(request, str(exc))
#             except UnicodeDecodeError:
#                 messages.error(request, "Encoding error occurred while processing request. Please try again.")
#             return redirect("addition_request_review")
#
#         # Use safe manager methods to handle encoding errors
#         pending_requests = AdditionRequest.objects.safe_filter(
#             status=AdditionRequestStatus.PENDING
#         ).select_related("requested_by")
#
#         recent_requests = AdditionRequest.objects.safe_filter(
#             status__in=[AdditionRequestStatus.APPROVED, AdditionRequestStatus.REJECTED]
#         ).select_related("requested_by", "reviewed_by")[:30]
#
#         return render(
#             request,
#             "requests/request_review.html",
#             {
#                 "request_nav": REQUEST_NAV,
#                 "pending_requests": pending_requests,
#                 "recent_requests": recent_requests,
#             },
#         )
#
#     except UnicodeDecodeError:
#         # Handle any remaining UnicodeDecodeError at the view level
#         messages.error(
#             request,
#             "An encoding error occurred while loading the page. "
#             "Some data may not be displayed due to encoding issues in the database."
#         )
#         return render(
#             request,
#             "requests/request_review.html",
#             {
#                 "request_nav": REQUEST_NAV,
#                 "pending_requests": AdditionRequest.objects.none(),
#                 "recent_requests": AdditionRequest.objects.none(),
#             },
#         )


@login_required
def live_fleet_mass_import(request):
    _ensure_superuser(request)

    form = LiveFleetBulkImportForm(request.POST or None, request.FILES or None)
    imported_count = None
    row_errors = []
    issues = []

    if request.method == "POST" and form.is_valid():
        rows_text = (form.cleaned_data.get("bulk_text") or "").strip()
        workbook = form.cleaned_data.get("workbook")
        try:
            if workbook:
                rows_text = rows_text_from_uploaded_workbook(workbook).strip()
        except ValueError as exc:
            form.add_error("workbook", str(exc))

        if not form.errors and not rows_text:
            form.add_error(None, "Paste rows or upload a completed .xlsx or .csv file.")

        if not form.errors:
            imported_count, row_errors, issues = bulk_import_live_vehicles(
                form.cleaned_data["operator"],
                rows_text,
            )
            if imported_count:
                messages.success(request, f"Imported {imported_count} vehicle row(s).")
            if not imported_count and not row_errors and not issues:
                messages.info(request, "Nothing imported.")

    return render(
        request,
        "vehicles/live_fleet_mass_import.html",
        {
            "form": form,
            "template_download_url": reverse("live_fleet_mass_import_template"),
            "imported_count": imported_count,
            "row_errors": row_errors,
            "issues": issues,
        },
    )


@login_required
def live_fleet_template_xlsx(request):
    _ensure_superuser(request)
    workbook = build_template_workbook()
    return _build_workbook_response(workbook, "live-fleet-template.xlsx")


@login_required
def live_fleet_operator_xlsx(request):
    _ensure_superuser(request)
    operator = get_object_or_404(Operator, pk=request.GET.get("operator"))
    workbook = build_template_workbook(data_rows=export_operator_fleet_rows(operator))
    filename = f"{operator.slug or operator.noc}-fleet.xlsx"
    return _build_workbook_response(workbook, filename)


@login_required
def add_vehicle_from_bustimes(request):
    """Superuser-only view to add a vehicle from bustimes.org API"""
    _ensure_superuser(request)
    
    if request.method == "POST":
        bustimes_url = request.POST.get("bustimes_url", "").strip()
        
        if not bustimes_url:
            messages.error(request, "Please enter a bustimes.org URL")
            return render(request, "vehicles/add_vehicle_from_bustimes.html")
        
        # Extract slug from URL
        if "bustimes.org/vehicles/" in bustimes_url:
            slug = bustimes_url.split("bustimes.org/vehicles/")[-1].split("?")[0].split("#")[0]
        else:
            messages.error(request, "Invalid bustimes.org vehicle URL")
            return render(request, "vehicles/add_vehicle_from_bustimes.html")
        
        try:
            # Call bustimes.org API
            api_url = f"https://bustimes.org/api/vehicles/?slug={slug}"
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if not data.get("results"):
                messages.error(request, "No vehicle found with that slug")
                return render(request, "vehicles/add_vehicle_from_bustimes.html")
            
            vehicle_data = data["results"][0]
            
            # Check if vehicle already exists
            if Vehicle.objects.filter(reg=vehicle_data.get("reg", "")).exists():
                messages.error(request, f"Vehicle with registration {vehicle_data.get('reg')} already exists")
                return render(request, "vehicles/add_vehicle_from_bustimes.html")
            
            # Create or get related objects
            operator = None
            if vehicle_data.get("operator"):
                operator, created = Operator.objects.get_or_create(
                    noc=vehicle_data["operator"]["id"],
                    defaults={"name": vehicle_data["operator"]["name"]}
                )
            
            vehicle_type = None
            if vehicle_data.get("vehicle_type"):
                vehicle_type, created = VehicleType.objects.get_or_create(
                    name=vehicle_data["vehicle_type"]["name"],
                    defaults={
                        "style": vehicle_data["vehicle_type"].get("style", ""),
                        "fuel": vehicle_data["vehicle_type"].get("fuel", ""),
                    }
                )
            
            livery = None
            if vehicle_data.get("livery"):
                livery, created = Livery.objects.get_or_create(
                    name=vehicle_data["livery"]["name"],
                    defaults={
                        "left_css": vehicle_data["livery"].get("left", ""),
                        "right_css": vehicle_data["livery"].get("right", ""),
                        "published": True,
                    }
                )
            
            # Create the vehicle
            vehicle = Vehicle.objects.create(
                slug=vehicle_data["slug"],
                code=vehicle_data.get("fleet_code", vehicle_data.get("fleet_number", "")),
                fleet_number=vehicle_data.get("fleet_number"),
                fleet_code=vehicle_data.get("fleet_code", ""),
                reg=vehicle_data.get("reg", ""),
                prev_registration=vehicle_data.get("previous_reg", ""),
                operator=operator,
                vehicle_type=vehicle_type,
                livery=livery,
                name=vehicle_data.get("name", ""),
                branding=vehicle_data.get("branding", ""),
                notes=vehicle_data.get("notes", ""),
                withdrawn=vehicle_data.get("withdrawn", False),
                is_manual=True,
                external_id=vehicle_data.get("id"),
            )
            
            messages.success(request, f"Successfully added vehicle: {vehicle}")
            return redirect("admin:vehicles_vehicle_change", vehicle.pk)
            
        except requests.RequestException as e:
            messages.error(request, f"Error fetching data from bustimes.org: {e}")
        except Exception as e:
            messages.error(request, f"Error creating vehicle: {e}")
    
    return render(request, "vehicles/add_vehicle_from_bustimes.html")

