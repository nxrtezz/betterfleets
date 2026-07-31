from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


TARGET_COLUMNS = (
    "operator_code",
    "external_id",
    "code",
    "fleet_number",
    "fleet_code",
    "registration",
    "prev_registration",
    "vehicle_type",
    "livery",
    "colours",
    "garage",
    "name",
    "branding",
    "notes",
    "withdrawn",
    "preserved",
    "fleet_support_vehicle",
    "vor",
    "awaiting_delivery",
    "trainer_vehicle",
    "demonstrator",
)

ROW_SPLIT_RE = re.compile(r"\s{2,}|\t+")
REGISTRATION_RE = re.compile(r"^[A-Z0-9]{2,8}$")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
VEHICLE_TYPE_RE = re.compile(
    r"Chassis Type:\s*(?P<chassis>.+?)\s+Body Type:\s*(?P<body>[^\n]+)",
    re.IGNORECASE,
)
SECTION_CAPTURE_RE = re.compile(
    r"(?P<label>Named Vehicles|Branding|Previous Registrations|Previous Owners):\s*(?P<body>.*?)(?=(?:\n[A-Z][A-Za-z ]+:)|\Z)",
    re.IGNORECASE | re.DOTALL,
)
ENTRY_RE = re.compile(
    r"(?P<key>[A-Za-z0-9\/-]+)\s*(?:-|:)\s*(?P<value>.+?)(?=(?:\s+[A-Za-z0-9\/-]+\s*(?:-|:)\s*)|$)"
)


@dataclass(slots=True)
class ParsedFleetRecord:
    operator_code: str = "EXLS"
    external_id: str = ""
    code: str = ""
    fleet_number: str = ""
    fleet_code: str = ""
    registration: str = ""
    prev_registration: str = ""
    vehicle_type: str = ""
    livery: str = ""
    colours: str = ""
    garage: str = ""
    name: str = ""
    branding: str = ""
    notes: str = ""
    withdrawn: bool = False
    preserved: bool = False
    fleet_support_vehicle: bool = False
    vor: bool = False
    awaiting_delivery: bool = False
    trainer_vehicle: bool = False
    demonstrator: bool = False
    source_page: int = 1
    raw_text: str = ""

    def to_model_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_pdf(source, default_operator_code: str = "EXLS") -> list[ParsedFleetRecord]:
    pages = extract_pages_from_pdf(source)
    return parse_text_pages(pages, default_operator_code=default_operator_code)


def extract_pages_from_pdf(source) -> list[str]:
    try:
        import pdfplumber
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "pdfplumber is required for PDF fleet imports. Add it to the environment before processing uploads."
        ) from exc

    extracted_pages: list[str] = []
    pdf_source = str(source) if isinstance(source, Path) else source
    with pdfplumber.open(pdf_source) as pdf:
        for page in pdf.pages:
            extracted_pages.append(page.extract_text() or "")
    return extracted_pages


def parse_text_pages(
    pages: list[str] | tuple[str, ...],
    default_operator_code: str = "EXLS",
) -> list[ParsedFleetRecord]:
    records: list[ParsedFleetRecord] = []
    current_vehicle_type = ""

    for page_number, page_text in enumerate(pages, start=1):
        normalised_text = _normalise_text(page_text)
        vehicle_type = _extract_vehicle_type(normalised_text) or current_vehicle_type
        if vehicle_type:
            current_vehicle_type = vehicle_type

        rows = _extract_vehicle_rows(normalised_text)
        metadata = _extract_metadata(normalised_text)

        for row in rows:
            row.vehicle_type = row.vehicle_type or current_vehicle_type
            row.operator_code = row.operator_code or default_operator_code
            row.source_page = page_number

            if previous_registration := metadata["previous_registrations"].get(row.fleet_number):
                row.prev_registration = previous_registration
            if name := metadata["named_vehicles"].get(row.fleet_number):
                row.name = name
            if branding := metadata["branding"].get(row.fleet_number):
                row.branding = branding
            if previous_owner := metadata["previous_owners"].get(row.fleet_number):
                row.notes = _append_note(row.notes, f"Previous owner: {previous_owner}")

            records.append(row)

    return records


def _normalise_text(page_text: str) -> str:
    page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
    return page_text.replace("\u00a0", " ")


def _extract_vehicle_type(page_text: str) -> str:
    match = VEHICLE_TYPE_RE.search(page_text)
    if not match:
        return ""
    parts = [match.group("chassis").strip(), match.group("body").strip()]
    return " ".join(part for part in parts if part)


def _extract_vehicle_rows(page_text: str) -> list[ParsedFleetRecord]:
    records: list[ParsedFleetRecord] = []
    in_table = False

    for raw_line in page_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "fleet no" in line.lower() and "reg no" in line.lower():
            in_table = True
            continue
        if not in_table:
            continue
        if re.match(r"^(Named Vehicles|Branding|Previous Registrations|Previous Owners):", line, re.IGNORECASE):
            break

        record = _parse_fleet_row(line)
        if record:
            records.append(record)

    return records


def _parse_fleet_row(line: str) -> ParsedFleetRecord | None:
    cells = [cell.strip() for cell in ROW_SPLIT_RE.split(line) if cell.strip()]
    if len(cells) >= 6:
        return _parse_row_from_cells(cells, line)
    return _parse_row_from_tokens(line)


def _parse_row_from_cells(cells: list[str], raw_line: str) -> ParsedFleetRecord | None:
    fleet_number = cells[0]
    registration = _normalise_registration(cells[1])
    if not fleet_number or not registration:
        return None

    record = ParsedFleetRecord(
        code=fleet_number,
        fleet_number=fleet_number,
        fleet_code=fleet_number,
        registration=registration,
        raw_text=raw_line,
    )
    if len(cells) >= 3:
        record.vehicle_type = ""
    if len(cells) >= 6:
        record.livery = cells[-1]
        record.garage = _normalise_garage(cells[-2])
    if len(cells) >= 7 and YEAR_RE.match(cells[-3]):
        pass
    return record


def _parse_row_from_tokens(raw_line: str) -> ParsedFleetRecord | None:
    tokens = raw_line.split()
    if len(tokens) < 6:
        return None
    fleet_number = tokens[0]
    registration = _normalise_registration(tokens[1])
    if not registration or not REGISTRATION_RE.match(registration):
        return None

    year_index = next((index for index, token in enumerate(tokens) if YEAR_RE.match(token)), None)
    if year_index is None or year_index + 2 >= len(tokens):
        return None

    remainder = tokens[year_index + 1 :]
    livery = remainder[-1]
    garage = " ".join(remainder[:-1])
    return ParsedFleetRecord(
        code=fleet_number,
        fleet_number=fleet_number,
        fleet_code=fleet_number,
        registration=registration,
        livery=livery,
        garage=_normalise_garage(garage),
        raw_text=raw_line,
    )


def _extract_metadata(page_text: str) -> dict[str, dict[str, str]]:
    metadata = {
        "named_vehicles": {},
        "branding": {},
        "previous_registrations": {},
        "previous_owners": {},
    }
    labels = {
        "named vehicles": "named_vehicles",
        "branding": "branding",
        "previous registrations": "previous_registrations",
        "previous owners": "previous_owners",
    }

    for match in SECTION_CAPTURE_RE.finditer(page_text):
        label = labels[match.group("label").strip().lower()]
        metadata[label] = _parse_keyed_section(match.group("body"))

    return metadata


def _parse_keyed_section(body: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        for chunk in re.split(r"\s*;\s*", line):
            chunk = chunk.strip()
            if not chunk:
                continue
            match = ENTRY_RE.match(chunk)
            if match:
                values[match.group("key")] = match.group("value").strip()
                continue
            tokens = chunk.split(None, 1)
            if len(tokens) == 2:
                values[tokens[0]] = tokens[1].strip()
    return values


def _normalise_registration(value: str) -> str:
    return value.upper().replace(" ", "")


def _normalise_garage(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if cleaned.upper().startswith("GSC "):
        return cleaned
    return f"GSC {cleaned}"


def _append_note(existing: str, extra: str) -> str:
    if not existing:
        return extra
    return f"{existing}\n{extra}"
