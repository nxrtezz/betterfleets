from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

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


def build_basic_fleet_workbook(operator, vehicles, advanced=False) -> Workbook:
    """Build a human-readable fleet export workbook with operator info header.
    
    Args:
        operator: Operator object with noc, slug, aka, slogan, organisation, group, government_authority
        vehicles: QuerySet of Vehicle objects
        advanced: If True, include advanced fields (engine, seating-capacity, gearbox)
    
    Returns:
        Workbook object with formatted sheets
    """
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Fleet"
    
    # Row 1: Operator basic info
    noc = getattr(operator, "noc", "") if operator else ""
    slug = getattr(operator, "slug", "") if operator else ""
    aka = getattr(operator, "aka", "") if operator else ""
    slogan = getattr(operator, "slogan", "") if operator else ""
    worksheet.append(["NOC", noc, "Slug", slug, "Aka", aka, "Slogan", slogan])
    
    # Row 2: Operator hierarchy
    organisation_name = ""
    group_name = ""
    gov_auth_name = ""
    
    if operator:
        if hasattr(operator, "organisation") and operator.organisation:
            organisation_name = getattr(operator.organisation, "name", "")
        if hasattr(operator, "group") and operator.group:
            group_name = getattr(operator.group, "name", "")
        if hasattr(operator, "government_authority") and operator.government_authority:
            gov_auth_name = getattr(operator.government_authority, "name", "")
    
    worksheet.append(["Organisation", organisation_name, "Group", group_name, "Government Authority", gov_auth_name])
    
    # Row 3: Empty row
    worksheet.append([])
    
    # Row 4: Column headers
    headers = ["Fleet Number", "Registration", "Vehicle type", "Livery", "Branding", "Features"]
    if advanced:
        headers.extend(["Engine", "Seating Capacity", "Gearbox"])
    worksheet.append(headers)
    
    # Make headers bold
    for cell in worksheet[4]:
        cell.font = Font(bold=True)
    
    # Vehicle data rows
    for vehicle in vehicles:
        vehicle_type = getattr(vehicle, "vehicle_type", None)
        vehicle_type_name = getattr(vehicle_type, "name", "") if vehicle_type else ""
        
        livery = getattr(vehicle, "livery", None)
        livery_name = getattr(livery, "name", "") if livery else ""
        
        features = ""
        if hasattr(vehicle, "features"):
            features = ", ".join([f.name for f in vehicle.features.all()])
        
        row = [
            getattr(vehicle, "fleet_number", "") or "",
            getattr(vehicle, "reg", "") or "",
            vehicle_type_name,
            livery_name,
            getattr(vehicle, "branding", "") or "",
            features,
        ]
        
        if advanced:
            # Get advanced fields from the advanced JSON field
            advanced_data = getattr(vehicle, "advanced", {}) or {}
            if not isinstance(advanced_data, dict):
                advanced_data = {}
            row.extend([
                advanced_data.get("engine", "") or "",
                advanced_data.get("seating-capacity", "") or "",
                advanced_data.get("gearbox", "") or "",
            ])
        
        worksheet.append(row)
    
    # Freeze panes below the header row (row 5)
    worksheet.freeze_panes = "A5"
    
    return workbook


def workbook_bytes(workbook: Workbook) -> bytes:
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
