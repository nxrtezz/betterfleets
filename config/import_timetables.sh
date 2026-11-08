#!/bin/sh
# Daily timetable import. Run inside the app container:
#   docker exec django_web sh /app/config/import_timetables.sh
# (mounted checkout means /app is the repo root)
#
# Each step runs even if a previous one failed; exit status is non-zero
# if any step failed. Requires BODS_API_KEY in the environment for the
# Bus Open Data step. TNDS is skipped - no FTP credentials are configured.

cd /app || exit 1

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

echo ""
if [ -n "$FAILED" ]; then
    echo "$(date -Is) completed with failures:$FAILED"
    exit 1
fi
echo "$(date -Is) all done"
