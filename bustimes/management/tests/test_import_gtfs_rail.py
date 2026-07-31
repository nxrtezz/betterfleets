import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from busstops.models import DataSource, Operator, Service, StopCode, StopPoint
from bustimes.models import RouteLink, Trip


def write_gtfs_zip(path: Path):
    files = {
        "agency.txt": "\n".join(
            (
                "agency_id,agency_name,agency_url,agency_timezone",
                "rail,Test Rail,https://example.com,Europe/London",
            )
        ),
        "routes.txt": "\n".join(
            (
                "route_id,agency_id,route_short_name,route_long_name,route_type",
                "wcml,rail,WCML,West Coast Main Line,2",
            )
        ),
        "trips.txt": "\n".join(
            (
                "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id,trip_short_name",
                "wcml,WKD,wcml-1,London Euston,0,wcml-shape,1A00",
            )
        ),
        "calendar.txt": "\n".join(
            (
                "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date",
                "WKD,1,1,1,1,1,0,0,20260101,20261231",
            )
        ),
        "stops.txt": "\n".join(
            (
                "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,platform_code",
                "EUS,EUS,London Euston,51.5282,-0.1337,1,",
                "RUG,RUG,Rugby,52.3783,-1.2509,0,3",
            )
        ),
        "stop_times.txt": "\n".join(
            (
                "trip_id,arrival_time,departure_time,stop_id,stop_sequence,pickup_type,drop_off_type,timepoint",
                "wcml-1,08:00:00,08:00:00,EUS,1,0,1,1",
                "wcml-1,08:49:00,08:50:00,RUG,2,0,0,1",
            )
        ),
        "shapes.txt": "\n".join(
            (
                "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence",
                "wcml-shape,51.5282,-0.1337,1",
                "wcml-shape,52.0000,-0.7000,2",
                "wcml-shape,52.3783,-1.2509,3",
            )
        ),
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


class ImportGtfsRailTest(TestCase):
    def test_import_gtfs_rail(self):
        with TemporaryDirectory() as directory:
            zip_path = Path(directory) / "rail.zip"
            write_gtfs_zip(zip_path)

            call_command(
                "import_gtfs_rail",
                str(zip_path),
                source_name="National Rail Test",
                operator_name="National Rail Test",
                operator_code="NRTEST",
            )

        source = DataSource.objects.get(name="National Rail Test")
        operator = Operator.objects.get(noc="NRTEST")
        service = Service.objects.get(source=source, service_code="wcml")
        trip = Trip.objects.get(route__service=service)

        self.assertEqual(service.mode, "rail")
        self.assertEqual(service.line_name, "WCML")
        self.assertEqual(service.description, "West Coast Main Line")
        self.assertEqual(trip.ticket_machine_code, "wcml-1")
        self.assertEqual(trip.vehicle_journey_code, "1A00")
        self.assertEqual(trip.destination_id, "rail-RUG")
        self.assertTrue(service.operator.filter(pk=operator.pk).exists())

        station = StopPoint.objects.get(atco_code="rail-EUS")
        platform = StopPoint.objects.get(atco_code="rail-RUG")
        self.assertEqual(station.stop_type, "RSE")
        self.assertEqual(platform.stop_type, "RPL")

        self.assertTrue(
            StopCode.objects.filter(source=source, stop=station, code="EUS").exists()
        )
        self.assertTrue(
            StopCode.objects.filter(source=source, stop=platform, code="RUG").exists()
        )
        self.assertEqual(RouteLink.objects.filter(service=service).count(), 1)
