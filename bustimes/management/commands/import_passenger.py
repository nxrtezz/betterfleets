"""Import timetable data "fresh from the cow" """

import csv
import io
import os
from datetime import datetime
from time import sleep
from urllib.parse import urljoin, urlparse

import bs4
import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from requests import Session

from busstops.models import DataSource, Operator, Ticket, TicketCategory

from ...download_utils import write_file
from ...models import TimetableDataSource, Version
from .import_bod_timetables import (
    clean_up,
    get_command,
    get_operator_ids,
    handle_file,
    logger,
)
from .import_gtfs import Command as GTFSImportCommand


def get_version(source, dates, url):
    filename = os.path.basename(urlparse(url).path)
    path = os.path.join(settings.DATA_DIR, filename)

    if not os.path.exists(path):
        response = requests.get(url, stream=True)
        url = response.url  # in case there was a redirect
        filename = os.path.basename(urlparse(url).path)
        path = os.path.join(settings.DATA_DIR, filename)

        if not os.path.exists(path):
            write_file(path, response)

    return Version.objects.update_or_create(
        {
            "start_date": dates[0],
            "end_date": dates[1],
            "url": url,
        },
        source=source,
        name=filename,
    )


def get_versions(session, source):
    versions = []
    try:
        response = session.get(source.url, timeout=61)
    except requests.RequestException as e:
        logger.warning(f"{source.url} {e}")
        sleep(5)
        return
    if not response.ok:
        logger.warning(f"{source.url} {response}")
        sleep(5)
        return

    soup = bs4.BeautifulSoup(response.text, "lxml")

    for heading in soup.find_all("h3"):
        if " to " not in heading.text:
            continue

        dates = (
            heading.text.removeprefix("Current Data (").removesuffix(")").split(" to ")
        )
        assert len(dates) == 2

        # Try to find GTFS first, then TXC as fallback
        gtfs_url = None
        txc_url = None

        for element in heading.next_siblings:
            if type(element) is not bs4.element.Tag:
                continue
            link = element.find("a")
            if not link:
                continue

            if link.text == "Download GTFS":
                gtfs_url = urljoin(response.url, link.attrs["href"])
            elif link.text == "Download TransXChange":
                txc_url = urljoin(response.url, link.attrs["href"])

            # Break once we have both or have moved past the buttons
            if gtfs_url and txc_url:
                break

        # Prioritize GTFS if available
        url = gtfs_url if gtfs_url else txc_url
        if url:
            versions.append(get_version(source, dates, url))
            break

    return versions


def get_mobile_products_url(session, source_url):
    """Get the mobile products CSV URL from a Passenger operator page"""
    try:
        response = session.get(source_url, timeout=61)
    except requests.RequestException as e:
        logger.warning(f"{source_url} {e}")
        return None
    if not response.ok:
        logger.warning(f"{source_url} {response}")
        return None

    soup = bs4.BeautifulSoup(response.text, "lxml")

    # Find the "Mobile Products" section
    for heading in soup.find_all("h2"):
        if "Mobile Products" in heading.text:
            for element in heading.next_siblings:
                if type(element) is not bs4.element.Tag:
                    continue
                link = element.find("a")
                if link and "Download CSV" in link.text:
                    return urljoin(response.url, link.attrs["href"])

    return None


def import_mobile_products(session, source_url, operator):
    """Import mobile products (tickets) from Passenger CSV"""
    csv_url = get_mobile_products_url(session, source_url)
    if not csv_url:
        logger.info(f"No mobile products found for {operator}")
        return

    try:
        response = session.get(csv_url, timeout=61)
    except requests.RequestException as e:
        logger.warning(f"{csv_url} {e}")
        return

    if not response.ok:
        logger.warning(f"{csv_url} {response}")
        return

    # Parse CSV
    csv_file = io.StringIO(response.text)
    reader = csv.DictReader(csv_file)

    # Track categories to avoid duplicates
    categories = {}

    for row in reader:
        category_id = row["category_id"]
        if category_id not in categories:
            categories[category_id], _ = TicketCategory.objects.update_or_create(
                id=category_id,
                defaults={
                    "title": row["category_title"],
                    "description": row["category_description"],
                },
            )

        Ticket.objects.update_or_create(
            id=row["topup_id"],
            operator=operator,
            defaults={
                "category": categories[category_id],
                "title": row["topup_title"],
                "description": row["topup_description"],
                "price_in_pence": int(row["topup_price_in_pence"]),
                "entitlement_type": row["topup_entitlement_type"],
                "entitlement_unit": row["topup_entitlement_unit"],
                "entitlement_value": (
                    int(row["topup_entitlement_value"])
                    if row["topup_entitlement_value"]
                    else None
                ),
                "entitlement_quantity": (
                    int(row["topup_entitlement_quantity"])
                    if row["topup_entitlement_quantity"]
                    else 1
                ),
                "start_date": (
                    datetime.strptime(row["topup_entitlement_start_date"], "%Y-%m-%d").date()
                    if row["topup_entitlement_start_date"]
                    else None
                ),
                "end_date": (
                    datetime.strptime(row["topup_entitlement_end_date"], "%Y-%m-%d").date()
                    if row["topup_entitlement_end_date"]
                    else None
                ),
                "passenger_class_name": row["topup_passenger_class_name"],
                "passenger_class_quantity": (
                    int(row["topup_passenger_class_quantity"])
                    if row["topup_passenger_class_quantity"]
                    else 1
                ),
            },
        )

    logger.info(f"Imported mobile products for {operator}")


def discover_passenger_operators(session):
    """Discover all operators from Passenger homepage"""
    try:
        response = session.get("https://data.discoverpassenger.com/", timeout=61)
    except requests.RequestException as e:
        logger.warning(f"https://data.discoverpassenger.com/ {e}")
        return []
    if not response.ok:
        logger.warning(f"https://data.discoverpassenger.com/ {response}")
        return []

    soup = bs4.BeautifulSoup(response.text, "lxml")
    operators = []

    # Find all operator links
    for link in soup.find_all("a", href=True):
        href = link.attrs["href"]
        if href.startswith("/operator/"):
            operator_slug = href.removeprefix("/operator/")
            operators.append(operator_slug)

    return operators


class Command(BaseCommand):
    @staticmethod
    def add_arguments(parser):
        parser.add_argument("operator_name", type=str, nargs="?")
        parser.add_argument(
            "--discover",
            action="store_true",
            help="Auto-discover and add all Passenger operators",
        )
        parser.add_argument(
            "--import-tickets",
            action="store_true",
            help="Import mobile products (tickets) from Passenger",
        )

    def handle(self, operator_name, *args, **options):
        command = get_command()
        session = Session()

        # Auto-discover mode
        if options.get("discover"):
            operator_slugs = discover_passenger_operators(session)
            logger.info(f"Discovered {len(operator_slugs)} Passenger operators")

            for slug in operator_slugs:
                url = f"https://data.discoverpassenger.com/operator/{slug}"
                # Check if source already exists
                if not TimetableDataSource.objects.filter(url=url).exists():
                    # Try to match operator by name
                    operator = Operator.objects.filter(
                        name__icontains=slug.replace("-", " ")
                    ).first()

                    if operator:
                        source = TimetableDataSource.objects.create(
                            name=f"{operator.name} (Passenger)",
                            url=url,
                            active=True,
                        )
                        source.operators.add(operator)
                        logger.info(f"Created source for {operator.name}")
                    else:
                        logger.warning(f"Could not find operator for {slug}")
            return

        prefix = "https://data.discoverpassenger.com/operator"
        suffix = "/open-data"

        timetable_data_sources = TimetableDataSource.objects.filter(
            Q(url__startswith=prefix) | Q(url__endswith=suffix), active=True
        )
        if operator_name:
            timetable_data_sources = timetable_data_sources.filter(name=operator_name)

        for source in timetable_data_sources:
            versions = get_versions(session, source)

            if versions:
                prefix = versions[0][0].name.split("_")[0]
                prefix = f"{prefix}_"  # eg 'transdevblazefield_'
                for filename in os.listdir(settings.DATA_DIR):
                    if filename.startswith(prefix) and not any(
                        filename == version.name for version, _ in versions
                    ):
                        os.remove(os.path.join(settings.DATA_DIR, filename))
            else:
                sleep(2)
                continue

            new_versions = any(modified for _, modified in versions)

            command.source, _ = DataSource.objects.get_or_create(
                {"name": source.name}, url=source.url
            )
            command.source.source = source

            if new_versions or operator_name:
                logger.info(source.name)

                operators = list(source.operators.values_list("noc", flat=True))

                command.source.datetime = timezone.now()
                command.region_id = source.region_id
                command.service_ids = set()
                command.route_ids = set()
                command.garages = {}

                for version, modified in versions:  # newest first
                    if modified or operator_name:
                        logger.info(version)
                        command.version = version

                        # Check if GTFS or TXC
                        if version.url.endswith(".zip") and "gtfs" in version.url.lower():
                            # Handle GTFS
                            gtfs_command = GTFSImportCommand()
                            gtfs_command.source = command.source
                            gtfs_command.handle_zipfile(
                                os.path.join(settings.DATA_DIR, version.name)
                            )
                        else:
                            # Handle TXC
                            handle_file(command, version.name, qualify_filename=True)

                clean_up(source, [command.source])

                operator_ids = get_operator_ids(command.source)
                logger.info(f"  {operator_ids}")

                foreign_operators = [o for o in operator_ids if o not in operators]
                logger.info(f"  {foreign_operators}")

            # Import mobile products if requested
            if options.get("import_tickets"):
                for operator in source.operators.all():
                    import_mobile_products(session, source.url, operator)

            # even if there are no new versions, delete non-current
            old_versions = source.version_set.filter(
                ~Q(id__in=[version.id for version, _ in versions])
            )
            command.source.route_set.filter(
                version__in=old_versions, service__isnull=False
            ).update(service=None, version=None)
            old_versions = old_versions.delete()

            if not (new_versions or operator_name):
                if old_versions[0]:
                    logger.info(source.name)
                else:
                    sleep(2)
                    continue
            logger.info(f"  {old_versions=}")

            # mark old services as not current
            old_services = command.source.service_set.filter(current=True, route=None)
            logger.info(f"  old services: {old_services.update(current=False)}")

            if new_versions or operator_name or old_versions:
                if not (new_versions or operator_name):
                    remaining_services = command.source.service_set.filter(current=True)
                    command.service_ids = remaining_services.values_list(
                        "id", flat=True
                    )
                command.finish_services()

            command.source.save()
