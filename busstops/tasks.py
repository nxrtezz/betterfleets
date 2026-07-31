import logging
import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from .views import operator_names
from . import popular_pages

logger = logging.getLogger(__name__)


@db_periodic_task(crontab(minute=9))
def update_popular_services():
    popular_services = (
        popular_pages.get_popular_services()
        .annotate(
            operators=operator_names,
        )
        .order_by("?")
    )[:10]

    # sort by string length for aesthetics
    popular_services = list(popular_services)
    popular_services.sort(key=lambda service: len(str(service)))

    cache.set("popular_services", popular_services, None)


@db_periodic_task(crontab(minute=17))
def sync_bustimes_journeys_hourly():
    call_command("sync_bustimes_journeys")


@db_periodic_task(crontab(minute=30, hour=3))
def import_timetables_daily():
    if os.environ.get("ENABLE_TIMETABLE_DAILY_IMPORT", "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    script_path = Path(settings.BASE_DIR) / "scripts" / "import-all-timetables.sh"
    if not script_path.exists():
        logger.warning("Daily timetable import skipped: %s does not exist.", script_path)
        return

    logger.info("Starting daily timetable import via %s", script_path)
    subprocess.run(
        ["bash", str(script_path)],
        check=True,
        cwd=settings.BASE_DIR,
        env=os.environ.copy(),
    )


@db_periodic_task(crontab(minute=45, hour=3, day_of_week="1"))
def refresh_tnds_weekly():
    if os.environ.get("ENABLE_TNDS_WEEKLY_IMPORT", "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return

    username = os.environ.get("TNDS_USERNAME", "")
    password = os.environ.get("TNDS_PASSWORD", "")
    if not username or not password:
        logger.warning("Weekly TNDS refresh skipped: missing TNDS credentials.")
        return

    logger.info("Starting weekly TNDS refresh.")
    call_command("refresh_tnds_data", username, password)
