#!/bin/sh
# Daily timetable import. Run inside the app container:
#   docker exec django_web sh /app/config/import_timetables.sh
# (mounted checkout means /app is the repo root)
#
# Each step runs even if a previous one failed; exit status is non-zero
# if any step failed. Requires BODS_API_KEY in the environment for the
# Bus Open Data step. TNDS credentials are read from /app/.env when present.

cd /app || exit 1

if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi

FAILED=""

run() {
    echo ""
    echo "=== $(date -Is) START: $* ==="
    if python manage.py "$@"; then
        echo "=== $(date -Is) OK: $* ==="
    else
        echo "=== $(date -Is) FAILED ($?): $* ==="
        FAILED="$FAILED $*"
    fi
}

run import_bod_timetables stagecoach
run import_bod_timetables ticketer
run import_passenger
run import_bod_timetables
run import_ni
run import_gtfs
run import_redfunnel_timetables
run cleanup_vehicle_codes

if [ -n "$TNDS_USERNAME" ] && [ -n "$TNDS_PASSWORD" ]; then
    run import_tnds "$TNDS_USERNAME" "$TNDS_PASSWORD"
else
    echo "=== $(date -Is) SKIP: import_tnds (no TNDS credentials in .env) ==="
fi

echo ""
if [ -n "$FAILED" ]; then
    echo "$(date -Is) completed with failures:$FAILED"
    exit 1
fi
echo "$(date -Is) all done"
