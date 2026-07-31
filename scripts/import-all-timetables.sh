#!/usr/bin/env bash
set -euo pipefail

ROOT="${BETTERFLEET_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LOCK_DIR="${BETTERFLEET_IMPORT_LOCK_DIR:-/tmp/betterfleet-timetable-import.lock}"

BODS_FLAGS=()
if [[ "${BODS_ALL_LOCAL_OPERATORS:-1}" == "1" ]]; then
    BODS_FLAGS+=(--all-local-operators)
fi
if [[ "${BODS_KEEP_UNPUBLISHED_SOURCES:-1}" == "1" ]]; then
    BODS_FLAGS+=(--keep-unpublished-sources)
fi

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing required command: $1" >&2
        exit 1
    }
}

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

need "$PYTHON_BIN"

cd "$ROOT"
if [[ ! -f manage.py ]]; then
    echo "manage.py not found in $ROOT" >&2
    exit 1
fi

mkdir "$LOCK_DIR" || {
    echo "A timetable import appears to be running already: $LOCK_DIR" >&2
    exit 1
}
trap finish EXIT SIGINT SIGTERM

if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
    manage migrate --noinput
fi

if [[ "${RUN_REFERENCE_IMPORTS:-1}" == "1" ]]; then
    manage nptg_new
    manage naptan_new
    manage naptan_new "Irish NaPTAN"
    manage import_noc
fi

if [[ "${RUN_TRANSXCHANGE:-1}" == "1" ]]; then
    if [[ "${DOWNLOAD_TRANSXCHANGE:-1}" == "1" ]]; then
        download "https://bodds-prod-coach-data.s3.eu-west-2.amazonaws.com/TxC-2.4.zip" "data/TNDS/NCSD.zip"
        download "https://tfl.gov.uk/tfl/syndication/feeds/journey-planner-timetables.zip" "data/TNDS/L.zip"
    fi

    if [[ -f data/TNDS/NCSD.zip ]]; then
        manage import_timetable_data transxchange data/TNDS/NCSD.zip
    else
        echo "Skipping NCSD TransXChange import; data/TNDS/NCSD.zip not found."
    fi

    if [[ -f data/TNDS/L.zip ]]; then
        manage import_timetable_data transxchange data/TNDS/L.zip
    else
        echo "Skipping TfL TransXChange import; data/TNDS/L.zip not found."
    fi
fi

if [[ "${RUN_BODS:-1}" == "1" ]]; then
    if [[ -z "${BODS_API_KEY:-}" ]]; then
        echo "Set BODS_API_KEY to import Bus Open Data Service timetables." >&2
        exit 1
    fi
    manage import_timetable_data bod "$BODS_API_KEY" "${BODS_FLAGS[@]}"
fi

if [[ "${RUN_SPECIAL_BODS:-1}" == "1" ]]; then
    manage import_timetable_data bod stagecoach
    manage import_timetable_data bod ticketer
fi

if [[ "${RUN_GTFS:-1}" == "1" ]]; then
    manage import_timetable_data gtfs
fi

if [[ "${TNDS_USERNAME:-}" != "" && "${TNDS_PASSWORD:-}" != "" ]]; then
    manage import_tnds "$TNDS_USERNAME" "$TNDS_PASSWORD"
else
    echo "Skipping legacy TNDS import; set TNDS_USERNAME and TNDS_PASSWORD to enable it."
fi

manage fix_service_operators --apply
manage update_search_indexes

echo "Timetable import complete."
