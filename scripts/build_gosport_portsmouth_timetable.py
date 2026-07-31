import os
from pathlib import Path

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.environ.get("TEMP", str(ROOT / "outputs")))
OUTPUT_PATH = OUTPUT_DIR / "gosport-portsmouth-timetable-import-v2.xlsx"

GOSPORT_CODE = "676767"
PORTSMOUTH_CODE = "676768"


def format_minutes(total_minutes: int) -> str:
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}:{minutes:02d}"


def build_rows():
    headers = [
        "import_key",
        "trip_id",
        "route_id",
        "line_name",
        "calendar_id",
        "inbound",
        "sequence",
        "stop_atco_code",
        "stop_name",
        "arrival",
        "departure",
        "pick_up",
        "set_down",
        "timing_status",
        "destination_atco_code",
        "headsign",
        "block",
        "ticket_machine_code",
        "vehicle_journey_code",
        "operator_noc",
        "garage_code",
        "vehicle_type_code",
    ]
    rows = [headers]

    trip_counter = 1

    for departure in range(5 * 60 + 30, 24 * 60 + 1, 15):
        trip_key = f"GOS-{trip_counter:03d}"
        rows.append(
            [
                trip_key,
                "",
                "",
                "Gosport-Portsmouth",
                "",
                "false",
                1,
                GOSPORT_CODE,
                "Gosport",
                "",
                format_minutes(departure),
                "true",
                "true",
                "PTP",
                PORTSMOUTH_CODE,
                "Portsmouth",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
        rows.append(
            [
                trip_key,
                "",
                "",
                "Gosport-Portsmouth",
                "",
                "false",
                2,
                PORTSMOUTH_CODE,
                "Portsmouth",
                format_minutes(departure + 7),
                "",
                "true",
                "true",
                "PTP",
                PORTSMOUTH_CODE,
                "Portsmouth",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
        trip_counter += 1

    for departure in range(5 * 60 + 37, 24 * 60, 15):
        trip_key = f"POR-{trip_counter:03d}"
        rows.append(
            [
                trip_key,
                "",
                "",
                "Gosport-Portsmouth",
                "",
                "true",
                1,
                PORTSMOUTH_CODE,
                "Portsmouth",
                "",
                format_minutes(departure),
                "true",
                "true",
                "PTP",
                GOSPORT_CODE,
                "Gosport",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
        rows.append(
            [
                trip_key,
                "",
                "",
                "Gosport-Portsmouth",
                "",
                "true",
                2,
                GOSPORT_CODE,
                "Gosport",
                format_minutes(departure + 7),
                "",
                "true",
                "true",
                "PTP",
                GOSPORT_CODE,
                "Gosport",
                "",
                "",
                "",
                "",
                "",
                "",
            ]
        )
        trip_counter += 1

    return rows


def main():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Timetable"

    for row in build_rows():
        sheet.append(row)

    instructions = workbook.create_sheet("Instructions")
    for row in [
        ["Assumption", "Value"],
        ["Pattern", "Daily service every 15 minutes"],
        ["Gosport departures", "05:30 to 24:00 inclusive"],
        ["Portsmouth departures", "05:37 to 23:52 inclusive"],
        ["Running time", "7 minutes each way"],
        ["Gosport ATCO", GOSPORT_CODE],
        ["Portsmouth ATCO", PORTSMOUTH_CODE],
        ["Format", "Ready for the admin timetable workbook importer"],
    ]:
        instructions.append(row)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    workbook.save(OUTPUT_PATH)
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
