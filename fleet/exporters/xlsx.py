from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook

from fleet.parsers.pdf_fleet_parser import TARGET_COLUMNS


def build_fleet_workbook(vehicles) -> Workbook:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Fleet"
    worksheet.append(list(TARGET_COLUMNS))

    for vehicle in vehicles:
        worksheet.append(
            [
                getattr(vehicle, "operator_code", ""),
                getattr(vehicle, "external_id", ""),
                getattr(vehicle, "code", ""),
                getattr(vehicle, "fleet_number", ""),
                getattr(vehicle, "fleet_code", ""),
                getattr(vehicle, "registration", ""),
                getattr(vehicle, "prev_registration", ""),
                getattr(vehicle, "vehicle_type", ""),
                getattr(vehicle, "livery", ""),
                getattr(vehicle, "colours", ""),
                getattr(vehicle, "garage", ""),
                getattr(vehicle, "name", ""),
                getattr(vehicle, "branding", ""),
                getattr(vehicle, "notes", ""),
                getattr(vehicle, "withdrawn", False),
                getattr(vehicle, "preserved", False),
                getattr(vehicle, "fleet_support_vehicle", False),
                getattr(vehicle, "vor", False),
                getattr(vehicle, "awaiting_delivery", False),
                getattr(vehicle, "trainer_vehicle", False),
                getattr(vehicle, "demonstrator", False),
            ]
        )

    worksheet.freeze_panes = "A2"
    return workbook


def workbook_bytes(workbook: Workbook) -> bytes:
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
