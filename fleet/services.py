from __future__ import annotations

from django.db import transaction

from fleet.models import FleetPDFUpload, FleetVehicle
from fleet.parsers.pdf_fleet_parser import parse_pdf


def process_pdf_upload(upload: FleetPDFUpload, default_operator_code: str = "EXLS") -> int:
    upload.status = FleetPDFUpload.Status.PROCESSING
    upload.error_message = ""
    upload.save(update_fields=["status", "error_message"])

    try:
        with upload.file.open("rb") as uploaded_file:
            parsed_records = parse_pdf(
                uploaded_file,
                default_operator_code=default_operator_code,
            )
        with transaction.atomic():
            upload.vehicles.all().delete()
            FleetVehicle.objects.bulk_create(
                [
                    FleetVehicle(source_pdf=upload, **record.to_model_dict())
                    for record in parsed_records
                ]
            )
            upload.status = FleetPDFUpload.Status.COMPLETED
            upload.error_message = ""
            upload.save(update_fields=["status", "error_message"])
    except Exception as exc:
        upload.status = FleetPDFUpload.Status.FAILED
        upload.error_message = str(exc)
        upload.save(update_fields=["status", "error_message"])
        raise

    return len(parsed_records)
