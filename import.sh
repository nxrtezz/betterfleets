#!/usr/bin/env bash
set -euo pipefail

ROOT="${BETTERFLEET_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LOCK_DIR="${BETTERFLEET_IMPORT_LOCK_DIR:-/tmp/betterfleet-import.lock}"
TNDS_USERNAME="noel@eeveeit.uk"
TNDS_PASSWORD="Google.2020"

BODS_FLAGS=()
if [[ "${BODS_ALL_LOCAL_OPERATORS:-1}" == "1" ]]; then
    BODS_FLAGS+=(--all-local-operators)
fi
if [[ "${BODS_KEEP_UNPUBLISHED_SOURCES:-1}" == "1" ]]; then
    BODS_FLAGS+=(--keep-unpublished-sources)
fi

manage() {
    "$PYTHON_BIN" manage.py "$@"
}

download() {
    local url="$1"
    local path="$2"

    mkdir -p "$(dirname "$path")"
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --time-cond "$path" --output "$path" "$url"
        return
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qN "$url" -O "$path"
        return
    fi
    echo "Missing curl or wget; cannot download $url" >&2
    exit 1
}

finish() {
    rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap finish EXIT SIGINT SIGTERM

cd "$ROOT"
if [[ ! -f manage.py ]]; then
    echo "manage.py not found in $ROOT" >&2
    exit 1
fi

mkdir "$LOCK_DIR" || {
    echo "An import appears to be running already: $LOCK_DIR" >&2
    exit 1
}

# Run migrations
if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
    manage migrate --noinput
fi

# Reference data imports (stops, regions, operators)
if [[ "${RUN_REFERENCE_IMPORTS:-1}" == "1" ]]; then
    manage nptg_new
    manage naptan_new
    manage naptan_new "Irish NaPTAN"
    manage import_noc
fi

# TransXChange imports (TNDS)
if [[ "${RUN_TRANSXCHANGE:-1}" == "1" ]]; then
    if [[ "${DOWNLOAD_TRANSXCHANGE:-1}" == "1" ]]; then
        download "https://bodds-prod-coach-data.s3.eu-west-2.amazonaws.com/TxC-2.4.zip" "data/TNDS/NCSD.zip"
        download "https://tfl.gov.uk/tfl/syndication/feeds/journey-planner-timetables.zip" "data/TNDS/L.zip"
    fi

    if [[ -f data/TNDS/NCSD.zip ]]; then
        echo "Importing NCSD.zip (TNDS)"
        manage import_timetable_data transxchange data/TNDS/NCSD.zip
    else
        echo "Skipping NCSD TransXChange import; data/TNDS/NCSD.zip not found."
    fi

    if [[ -f data/TNDS/L.zip ]]; then
        echo "Importing L.zip (TfL)"
        manage import_timetable_data transxchange data/TNDS/L.zip
    else
        echo "Skipping TfL TransXChange import; data/TNDS/L.zip not found."
    fi
fi

# BODS imports (Bus Open Data Service)
if [[ "${RUN_BODS:-1}" == "1" ]]; then
    if [[ -z "${BODS_API_KEY:-}" ]]; then
        echo "Skipping BODS import; set BODS_API_KEY to import Bus Open Data Service timetables." >&2
    else
        echo "Importing BODS timetables"
        manage import_timetable_data bod "$BODS_API_KEY" "${BODS_FLAGS[@]}"
    fi
fi

# Special BODS imports (Stagecoach, Ticketer)
if [[ "${RUN_SPECIAL_BODS:-1}" == "1" ]]; then
    echo "Importing special BODS sources (Stagecoach, Ticketer)"
    manage import_timetable_data bod stagecoach
    manage import_timetable_data bod ticketer
fi

# Passenger imports
if [[ "${RUN_PASSENGER:-1}" == "1" ]]; then
    echo "Importing Passenger timetables"
    manage import_passenger
fi

# GTFS imports
if [[ "${RUN_GTFS:-1}" == "1" ]]; then
    echo "Importing GTFS timetables"
    manage import_timetable_data gtfs
fi

# Legacy TNDS import
if [[ "${TNDS_USERNAME:-}" != "" && "${TNDS_PASSWORD:-}" != "" ]]; then
    echo "Importing legacy TNDS data"
    manage import_tnds "$TNDS_USERNAME" "$TNDS_PASSWORD"
else
    echo "Skipping legacy TNDS import; set TNDS_USERNAME and TNDS_PASSWORD to enable it."
fi

# Fix service operators and update search indexes
manage fix_service_operators --apply
manage update_search_indexes

echo "Timetable import complete."
