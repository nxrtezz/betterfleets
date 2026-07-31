from __future__ import annotations

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from fleet.exporters.xlsx import build_fleet_workbook, workbook_bytes
from fleet.live_import import build_import_rows, commit_import_rows
from fleet.matching import match_garage, match_operator
from fleet.models import FleetPDFUpload, FleetRideLog, FleetVehicle
from fleet.services import process_pdf_upload


def _xlsx_response(filename: str, vehicles) -> HttpResponse:
    workbook = build_fleet_workbook(vehicles)
    response = HttpResponse(
        workbook_bytes(workbook),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@admin.register(FleetPDFUpload)
class FleetPDFUploadAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "original_filename",
        "uploaded_at",
        "status",
        "operator_intention",
        "vehicle_count",
        "live_import_link",
        "download_link",
        "short_error",
    )
    list_filter = ("status", "uploaded_at")
    readonly_fields = (
        "uploaded_at",
        "status",
        "error_message",
        "download_link",
        "live_import_link",
        "operator_intention",
        "garage_intentions",
    )
    actions = ("process_selected_pdfs", "export_extracted_vehicles_to_xlsx")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/export.xlsx",
                self.admin_site.admin_view(self.export_view),
                name="fleet_fleetpdfupload_export_xlsx",
            ),
            path(
                "<path:object_id>/import-live/",
                self.admin_site.admin_view(self.import_live_view),
                name="fleet_fleetpdfupload_import_live",
            ),
        ]
        return custom_urls + urls

    @admin.display(description="Vehicles")
    def vehicle_count(self, obj):
        return obj.vehicles.count()

    @admin.display(description="Operator match")
    def operator_intention(self, obj):
        operator_code = obj.vehicles.exclude(operator_code="").values_list(
            "operator_code", flat=True
        ).first()
        if not operator_code:
            return "Operator match will appear after processing."
        return match_operator(operator_code).label

    @admin.display(description="Depot matches")
    def garage_intentions(self, obj):
        previews = []
        seen = set()
        for operator_code, garage in obj.vehicles.values_list("operator_code", "garage"):
            key = (operator_code, garage)
            if key in seen or not garage:
                continue
            seen.add(key)
            previews.append(match_garage(garage, operator_code).label)
        if not previews:
            return "Depot matches will appear after processing."
        return format_html("<br>".join(previews))

    @admin.display(description="Download")
    def download_link(self, obj):
        if not obj.pk or not obj.vehicles.exists():
            return "-"
        url = reverse("admin:fleet_fleetpdfupload_export_xlsx", args=(obj.pk,))
        return format_html('<a href="{}">Download XLSX</a>', url)

    @admin.display(description="Live import")
    def live_import_link(self, obj):
        if not obj.pk or not obj.vehicles.exists():
            return "-"
        url = reverse("admin:fleet_fleetpdfupload_import_live", args=(obj.pk,))
        return format_html('<a class="button" href="{}">Preview live import</a>', url)

    @admin.display(description="Error")
    def short_error(self, obj):
        if not obj.error_message:
            return ""
        return obj.error_message[:80]

    @admin.action(description="Process selected PDFs")
    def process_selected_pdfs(self, request, queryset):
        processed = 0
        failed = 0
        for upload in queryset:
            try:
                process_pdf_upload(upload)
                processed += 1
            except Exception:
                failed += 1

        if processed:
            self.message_user(
                request,
                f"Processed {processed} PDF upload{'s' if processed != 1 else ''}.",
                level=messages.SUCCESS,
            )
        if failed:
            self.message_user(
                request,
                f"{failed} PDF upload{'s' if failed != 1 else ''} failed. Open the upload record for the error message.",
                level=messages.WARNING,
            )

    @admin.action(description="Export extracted vehicles to XLSX")
    def export_extracted_vehicles_to_xlsx(self, request, queryset):
        vehicles = FleetVehicle.objects.filter(source_pdf__in=queryset).order_by(
            "source_pdf_id", "source_page", "fleet_number", "fleet_code", "code"
        )
        return _xlsx_response("fleet-pdf-export.xlsx", vehicles)

    def export_view(self, request, object_id):
        upload = self.get_object(request, object_id)
        if upload is None:
            raise PermissionDenied
        filename_root = (upload.original_filename or f"fleet-upload-{upload.pk}").rsplit(".", 1)[0]
        vehicles = upload.vehicles.order_by("source_page", "fleet_number", "fleet_code", "code")
        return _xlsx_response(f"{filename_root}.xlsx", vehicles)

    def import_live_view(self, request, object_id):
        upload = self.get_object(request, object_id)
        if upload is None:
            raise PermissionDenied

        rows = build_import_rows(upload)
        summary = None

        if request.method == "POST" and request.POST.get("action") == "commit":
            summary = commit_import_rows(rows)
            if summary.created or summary.updated:
                self.message_user(
                    request,
                    f"Live fleet import complete: created {summary.created}, updated {summary.updated}, errors {summary.errors}",
                    level=messages.SUCCESS,
                )
            elif summary.errors:
                self.message_user(
                    request,
                    f"No live vehicles imported. {summary.errors} row(s) had errors.",
                    level=messages.WARNING,
                )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": upload,
            "upload": upload,
            "title": f"Preview live fleet import for {upload}",
            "rows": rows,
            "can_commit": any(not row["errors"] for row in rows),
            "summary": summary,
        }
        return TemplateResponse(
            request,
            "admin/fleet/fleetpdfupload/import_live_fleet.html",
            context,
        )


@admin.register(FleetVehicle)
class FleetVehicleAdmin(admin.ModelAdmin):
    list_display = (
        "operator_code",
        "operator_match_status",
        "code",
        "fleet_number",
        "fleet_code",
        "registration",
        "vehicle_type",
        "livery",
        "garage",
        "garage_match_status",
        "name",
        "branding",
        "withdrawn",
        "preserved",
        "source_pdf",
        "source_page",
        "updated_at",
    )
    list_editable = (
        "code",
        "fleet_number",
        "fleet_code",
        "registration",
        "vehicle_type",
        "livery",
        "garage",
        "name",
        "branding",
        "withdrawn",
        "preserved",
    )
    list_filter = ("operator_code", "livery", "garage", "withdrawn", "preserved", "source_pdf")
    search_fields = (
        "fleet_number",
        "registration",
        "fleet_code",
        "vehicle_type",
        "livery",
        "garage",
    )
    readonly_fields = ("created_at", "updated_at")
    actions = ("export_selected_to_xlsx",)

    @admin.display(description="Operator intention")
    def operator_match_status(self, obj):
        return obj.operator_match().label

    @admin.display(description="Depot intention")
    def garage_match_status(self, obj):
        return obj.garage_match().label

    @admin.action(description="Export selected vehicles to XLSX")
    def export_selected_to_xlsx(self, request, queryset):
        vehicles = queryset.order_by("source_pdf_id", "source_page", "fleet_number", "fleet_code", "code")
        return _xlsx_response("fleet-vehicles.xlsx", vehicles)


@admin.register(FleetRideLog)
class FleetRideLogAdmin(admin.ModelAdmin):
    list_display = ("user", "vehicle", "created_at")
    list_filter = ("user", "created_at", "vehicle__operator", "vehicle__vehicle_type")
    raw_id_fields = ("user", "vehicle")
    search_fields = (
        "user__username",
        "user__email",
        "vehicle__code",
        "vehicle__fleet_code",
        "vehicle__reg",
    )
    actions = ("delete_logs_for_user_and_operators",)

    @admin.action(description="Delete logs for user (keep selected operators)")
    def delete_logs_for_user_and_operators(self, request, queryset):
        if request.method == "POST" and request.POST.get("post"):
            user_id = request.POST.get("user_id")
            operator_ids_to_keep = request.POST.getlist("operator_ids")
            
            if not user_id:
                self.message_user(request, "No user selected.", level=messages.ERROR)
                return
            
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                self.message_user(request, "User not found.", level=messages.ERROR)
                return
            
            logs_to_delete = queryset.filter(user=user)
            if operator_ids_to_keep:
                logs_to_delete = logs_to_delete.exclude(vehicle__operator_id__in=operator_ids_to_keep)
            
            count = logs_to_delete.count()
            logs_to_delete.delete()
            
            self.message_user(
                request,
                f"Deleted {count} ride log{'s' if count != 1 else ''} for {user.username}.",
                level=messages.SUCCESS,
            )
            return
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        from busstops.models import Operator
        
        users = User.objects.filter(fleet_ride_logs__isnull=False).distinct().order_by("username")
        operators = Operator.objects.filter(vehicle__fleet_ride_logs__isnull=False).distinct().order_by("name")
        
        context = {
            **self.admin_site.each_context(request),
            "title": "Delete logs for user (keep selected operators)",
            "queryset": queryset,
            "users": users,
            "operators": operators,
            "action_checkbox_name": "_selected_action",
            "media": self.media,
        }
        
        return TemplateResponse(
            request,
            "admin/fleet/fleetridelog/delete_logs_for_user.html",
            context,
        )
