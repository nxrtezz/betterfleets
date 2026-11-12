"""Pure-python parsing for Red Funnel PDF timetables.

Separated from the django management command so it can be tested
without a database. See import_redfunnel_timetables for usage.
"""

import io
import re
from datetime import date
from urllib.parse import urljoin

import pdfplumber
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

PAGE_URL = "https://www.redfunnel.co.uk/isle-of-wight-ferry/plan/timetables"
USER_AGENT = "betterfleets/1.0 (+https://eeveeit.uk)"

# ferry terminal stop points (synthetic ATCO codes - these aren't NaPTAN stops)
TERMINALS = {
    "southampton t1": ("RF-SOU-T1", "Southampton (Red Funnel Terminal)", -1.4054, 50.8944),
    "southampton t2": ("RF-SOU-T2", "Southampton (Red Jet Terminal)", -1.4045, 50.9018),
    "east cowes": ("RF-EAS", "East Cowes (Vehicle Ferry)", -1.2907, 50.7595),
    "west cowes": ("RF-WES", "West Cowes (Red Jet)", -1.2215, 50.7765),
}

# which service/line each direction belongs to, terminal keys, crossing time (mins)
DIRECTIONS = {
    "southampton to east cowes": ("RedFunnel", "southampton t1", "east cowes", 60),
    "east cowes to southampton": ("RedFunnel", "east cowes", "southampton t1", 60),
    "southampton t2 to west cowes": ("RedJet", "southampton t2", "west cowes", 28),
    "west cowes to southampton t2": ("RedJet", "west cowes", "southampton t2", 28),
}

DAY_TYPES = {
    "mon to fri": {"mon": True, "tue": True, "wed": True, "thu": True, "fri": True},
    "mon to sat": {
        "mon": True, "tue": True, "wed": True, "thu": True, "fri": True, "sat": True
    },
    "sat": {"sat": True},
    "sun": {"sun": True},
    "sun / bank holiday": {"sun": True, "bank_holidays": True},
}
DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

TIME_RE = re.compile(r"^(\d{2})(\d{2})\*?$")
DIRECTION_RE = re.compile(r"^(.+?)\s+to\s+(.+?)$")
VALIDITY_RE = re.compile(
    r"(\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?|\d{1,2})"
    r"\s*[-–—]\s*"
    r"(\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?|\d{1,2})"
)


def pdf_rows(content: bytes):
    """yield text rows (top, text) from the first page of a pdf"""
    rows = {}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        page = pdf.pages[0]
        for word in page.extract_words():
            key = round(word["top"] / 3)
            rows.setdefault(key, []).append(word)
    for key in sorted(rows):
        words = sorted(rows[key], key=lambda w: w["x0"])
        yield key * 3, " ".join(w["text"] for w in words)


def parse_hhmm(token: str):
    m = TIME_RE.match(token)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 3600 + minute * 60


def _parse_date(raw: str, default_year: int):
    try:
        return date_parser.parse(
            raw,
            dayfirst=True,
            default=date_parser.parse(f"1 Jan {default_year}"),
        )
    except (ValueError, OverflowError):
        return None


def parse_validity(text: str):
    """'3 Nov 2026 - 21 Mar 2027' -> (date, date); tolerates missing years"""
    match = VALIDITY_RE.search(text)
    if not match:
        return None
    start_raw, end_raw = match.groups()
    end = _parse_date(end_raw, default_year=2000)
    if end is None:
        return None
    if re.fullmatch(r"\d{1,2}", start_raw):
        # '2 - 23 Nov 2026' -> same month as the end date
        start = _parse_date(f"{start_raw} {end:%b %Y}", default_year=end.year)
    else:
        start = _parse_date(start_raw, default_year=end.year)
    if start is None:
        return None
    if start > end:
        # '24 Nov - 10 Jan 2027' -> start year is the previous year
        start = _parse_date(start_raw, default_year=end.year - 1)
        if start is None or start > end:
            return None
    return start.date(), end.date()


def parse_pdf(content: bytes):
    """returns (validity, {direction_key: {day_type: [seconds]}})"""
    validity = None
    current_direction = None
    schedules = {}

    for _, text in pdf_rows(content):
        if validity is None and re.search(r"\d{4}", text) and "-" in text:
            candidate = parse_validity(text)
            if candidate:
                validity = candidate
                continue
        if "Crossing Time" in text or "Timetable" in text.split()[:3]:
            continue

        m = DIRECTION_RE.match(text)
        if m:
            key = f"{m.group(1)} to {m.group(2)}".lower()
            if key in DIRECTIONS:
                current_direction = key
                schedules.setdefault(key, {})
                continue

        if current_direction is None:
            continue

        day_type = next(
            (label for label in DAY_TYPES if text.lower().startswith(label)),
            None,
        )
        if day_type is None:
            continue

        times = [
            seconds
            for token in text.split()
            if (seconds := parse_hhmm(token)) is not None
        ]
        if times:
            schedules[current_direction][day_type] = sorted(set(times))

    return validity, schedules


SECTIONS = ("Vehicle Ferry Service", "Red Jet Hi-Speed Service")


def find_pdfs(session):
    """scrape the timetables page for pdf links -> {filename: url}

    only keeps links inside the Vehicle Ferry / Red Jet sections -
    the page also links unrelated PDFs (privacy notices etc.)"""
    response = session.get(PAGE_URL, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    pdfs = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" not in href.lower():
            continue
        # nearest ancestor mentioning a timetable section; the page
        # body mentions both, so require exactly one marker
        parent = a.parent
        for _ in range(8):
            if parent is None:
                break
            text = parent.get_text(" ", strip=True)
            hits = [s for s in SECTIONS if s in text]
            if len(hits) == 1:
                break
            parent = parent.parent
        else:
            continue
        if parent is None or len(hits) != 1:
            continue
        pdfs[href.rsplit("/", 1)[-1]] = urljoin(PAGE_URL, href)
    return pdfs
