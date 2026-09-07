#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-1}" != "0" ]; then
    ./manage.py migrate_with_lock
fi

exec "$@"
