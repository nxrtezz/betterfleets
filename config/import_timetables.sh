#!/bin/sh
cd /app || exit 1
# Lock inherited by the complete run; concurrent cron/manual runs are refused.
if [ "$BF_IMPORT_LOCKED" != 1 ]; then
    export BF_IMPORT_LOCKED=1
    exec python -c 'import fcntl,os; f=open("/app/data/nightly-import.lock","w"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); os.set_inheritable(f.fileno(),True); os.execvp("sh",["sh","/app/config/import_timetables.sh"])'
fi
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi
FAILED=""
status() {
    BF_IMPORT_STATE="$1" BF_IMPORT_FAILURES="$FAILED" python -c 'import json,os,time; from pathlib import Path; p=Path("/app/data/nightly-import-status.json"); t=p.with_suffix(".tmp"); t.write_text(json.dumps({"state":os.environ["BF_IMPORT_STATE"],"updated":time.time(),"failures":os.environ["BF_IMPORT_FAILURES"]})); t.replace(p)'
}
run() {
    label="$1"
    shift
    echo "=== $(date -Is) START: $label ==="
    status running
    if timeout --signal=TERM --kill-after=60s 4h python manage.py "$@"; then
        echo "=== $(date -Is) OK: $label ==="
    else
        rc=$?
        echo "=== $(date -Is) FAILED ($rc): $label ==="
        FAILED="$FAILED $label"
    fi
}
status running
run stagecoach import_bod_timetables stagecoach
run ticketer import_bod_timetables ticketer
run passenger import_passenger
# Dataset IDs are stable; discover all operators actually producing tracking.
run bods-tracking import_bod_timetables --auto-discover --tracking-only
run northern-ireland import_ni
run gtfs import_gtfs
run ember-timetables import_gtfs_ember
run flixbus-timetables import_gtfs_flixbus
run redfunnel import_redfunnel_timetables
run vehicle-codes cleanup_vehicle_codes
if [ -n "$TNDS_USERNAME" ] && [ -n "$TNDS_PASSWORD" ]; then
    run tnds import_tnds "$TNDS_USERNAME" "$TNDS_PASSWORD"
fi
if [ -n "$FAILED" ]; then
    status failed
    echo "$(date -Is) completed with failures:$FAILED"
    exit 1
fi
status succeeded
echo "$(date -Is) all done"
