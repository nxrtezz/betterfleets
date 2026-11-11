"""
Red Funnel timetable importer.

Scrapes https://www.redfunnel.co.uk/isle-of-wight-ferry/plan/timetables
for the Vehicle Ferry and Red Jet PDF timetables, parses the departure
grids (see vehicles/redfunnel_timetable.py) and creates
Route/Calendar/Trip/StopTime records so live journeys can be matched
to scheduled sailings.
"""

import hashlib
import logging
from datetime import timedelta

import requests
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand

from busstops.models import DataSource, Operator, Service, StopPoint
from bustimes.models import (
    BankHolidayDate,
    Calendar,
    CalendarBankHoliday,
    Route,
    StopTime,
    Trip,
)
from vehicles.redfunnel_timetable import (
    DAY_KEYS,
    DAY_TYPES,
    DIRECTIONS,
    PAGE_URL,
    TERMINALS,
    USER_AGENT,
    find_pdfs,
    parse_pdf,
)

logger = logging.getLogger(__name__)

SOURCE_NAME = "Red Funnel"
OPERATOR_NOC = "RF"
TIMEZONE = "Europe/London"


def get_stop(source, key):
    atco, name, lon, lat = TERMINALS[key]
    stop, _ = StopPoint.objects.update_or_create(
        atco_code=atco,
        defaults={
            "common_name": name,
            "short_common_name": name,
            "latlong": Point(lon, lat, srid=4326),
            "source": source,
            "timezone": TIMEZONE,
            "town": "Southampton" if "southampton" in key else "Cowes",
        },
    )
    return stop


def get_service(operator, source, line_name):
    service = Service.objects.filter(
        line_name__iexact=line_name, operator=operator, current=True
    ).first()
    if service is None:
        service = Service.objects.create(
            line_name=line_name,
            line_brand="Red Funnel",
            description=line_name,
            mode="ferry",
            source=source,
        )
        service.operator.add(operator)
    return service


def get_calendar(source, day_flags, start, end, label):
    calendar, created = Calendar.objects.get_or_create(
        source=source,
        start_date=start,
        end_date=end,
        summary=label,
        **{day: day_flags.get(day, False) for day in DAY_KEYS},
    )
    if created and day_flags.get("bank_holidays"):
        for bh_date in BankHolidayDate.objects.filter(
            date__gte=start, date__lte=end
        ).select_related("bank_holiday"):
            CalendarBankHoliday.objects.get_or_create(
                calendar=calendar,
                bank_holiday=bh_date.bank_holiday,
                defaults={"operation": True},
            )
    return calendar


class Command(BaseCommand):
    help = "Import Red Funnel ferry/Red Jet PDF timetables"

    def add_arguments(self, parser):
        parser.add_argument("--url", help="import a single PDF url instead of scraping")

    def handle(self, *args, **options):
        source, _ = DataSource.objects.get_or_create(
            name=SOURCE_NAME, defaults={"url": PAGE_URL}
        )
        operator = Operator.objects.get(noc=OPERATOR_NOC)

        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

        if options.get("url"):
            pdfs = {options["url"].rsplit("/", 1)[-1]: options["url"]}
        else:
            pdfs = find_pdfs(session)
            logger.info("found %d timetable pdfs", len(pdfs))

        stops = {key: get_stop(source, key) for key in TERMINALS}

        for filename, url in pdfs.items():
            try:
                self.import_pdf(session, source, operator, stops, filename, url)
            except Exception:
                logger.exception("failed to import %s", filename)

    def import_pdf(self, session, source, operator, stops, filename, url):
        response = session.get(url, timeout=60)
        response.raise_for_status()
        content = response.content
        file_hash = hashlib.sha1(content).hexdigest()

        route = Route.objects.filter(source=source, code=filename).first()
        if route and route.file_hash == file_hash:
            logger.info("%s unchanged, skipping", filename)
            return

        validity, schedules = parse_pdf(content)
        if validity is None:
            logger.error("%s: could not parse validity dates", filename)
            return
        if not schedules:
            logger.error("%s: no schedules parsed", filename)
            return

        start_date, end_date = validity
        logger.info(
            "%s: validity %s - %s, directions %s",
            filename, start_date, end_date, list(schedules),
        )

        # each pdf covers a single service - take it from the first direction
        line_name = DIRECTIONS[next(iter(schedules))][0]
        service = get_service(operator, source, line_name)

        if route is None:
            route = Route(source=source, code=filename, service=service)
        else:
            # unchanged content was handled above; a changed pdf gets fresh trips
            Trip.objects.filter(route=route).delete()
            route.service = service

        route.line_name = line_name
        route.line_brand = "Red Funnel"
        route.description = f"{line_name} timetable {filename}"
        route.start_date = start_date
        route.end_date = end_date
        route.timezone = TIMEZONE
        route.public_use = True
        route.file_hash = file_hash

        trip_count = 0
        for direction, day_schedules in schedules.items():
            _, origin_key, dest_key, crossing = DIRECTIONS[direction]
            origin_stop = stops[origin_key]
            dest_stop = stops[dest_key]
            inbound = "southampton" not in direction.split(" to ")[0]
            route.origin = origin_stop.common_name
            route.destination = dest_stop.common_name

            for day_label, times in day_schedules.items():
                calendar = get_calendar(
                    source, DAY_TYPES[day_label], start_date, end_date, day_label
                )
                for seconds in times:
                    arrival = seconds + crossing * 60
                    trip = Trip.objects.create(
                        route=route,
                        calendar=calendar,
                        start=timedelta(seconds=seconds),
                        end=timedelta(seconds=arrival),
                        headsign=dest_stop.common_name,
                        destination=dest_stop,
                        inbound=inbound,
                        operator=operator,
                    )
                    StopTime.objects.create(
                        trip=trip,
                        stop=origin_stop,
                        departure=timedelta(seconds=seconds),
                        sequence=1,
                    )
                    StopTime.objects.create(
                        trip=trip,
                        stop=dest_stop,
                        arrival=timedelta(seconds=arrival),
                        sequence=2,
                    )
                    trip_count += 1

        route.save()
        logger.info("%s: imported %d trips", filename, trip_count)
