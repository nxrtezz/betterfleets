from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from busstops.models import DataSource, Region, Service
from bustimes.models import Route, TimetableDataSource


class RefreshTransXChangeSourcesTests(TestCase):
    def test_requires_selector_or_all(self):
        with self.assertRaisesMessage(
            CommandError,
            "Pass at least one source selector or use --all.",
        ):
            call_command("refresh_transxchange_sources")

    @mock.patch("bustimes.management.commands.refresh_transxchange_sources.get_sha1")
    @mock.patch("bustimes.management.commands.refresh_transxchange_sources.handle_file")
    @mock.patch("bustimes.management.commands.refresh_transxchange_sources.download")
    def test_refreshes_selected_source_only(
        self,
        mock_download,
        mock_handle_file,
        mock_get_sha1,
    ):
        mock_get_sha1.return_value = "new-sha1"

        region = Region.objects.create(pk="SE", name="South East")
        selected_source = TimetableDataSource.objects.create(
            name="BHBC",
            url="https://www.buses.co.uk/open-data/network/current",
            region=region,
            active=True,
        )
        other_timetable_source = TimetableDataSource.objects.create(
            name="OTHER",
            url="https://example.com/other.zip",
            region=region,
            active=True,
        )

        selected_data_source = DataSource.objects.create(
            name="BHBC",
            url=selected_source.url,
            sha1="old-sha1",
            source=selected_source,
        )
        other_data_source = DataSource.objects.create(
            name="OTHER",
            url=other_timetable_source.url,
            sha1="other-sha1",
            source=other_timetable_source,
        )

        selected_service = Service.objects.create(
            service_code="bhbc-1",
            line_name="1",
            region=region,
            source=selected_data_source,
        )
        other_service = Service.objects.create(
            service_code="other-1",
            line_name="2",
            region=region,
            source=other_data_source,
        )

        Route.objects.create(service=selected_service, source=selected_data_source, line_name="1")
        Route.objects.create(service=other_service, source=other_data_source, line_name="2")

        with TemporaryDirectory() as directory:
            with override_settings(DATA_DIR=Path(directory)):
                call_command("refresh_transxchange_sources", "BHBC")

        self.assertFalse(Service.objects.filter(pk=selected_service.pk).exists())
        self.assertTrue(Service.objects.filter(pk=other_service.pk).exists())

        selected_data_source.refresh_from_db()
        other_data_source.refresh_from_db()

        self.assertEqual(selected_data_source.sha1, "new-sha1")
        self.assertEqual(other_data_source.sha1, "other-sha1")
        self.assertEqual(selected_data_source.source_id, selected_source.id)

        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_handle_file.call_count, 1)

    @mock.patch(
        "bustimes.management.commands.refresh_transxchange_sources.Command.import_source"
    )
    @mock.patch(
        "bustimes.management.commands.refresh_transxchange_sources.Command.purge_existing_rows"
    )
    @mock.patch(
        "bustimes.management.commands.refresh_transxchange_sources.download"
    )
    def test_all_refresh_skips_passenger_and_ticketer_sources(
        self,
        mock_download,
        mock_purge_existing_rows,
        mock_import_source,
    ):
        mock_purge_existing_rows.return_value = {
            "sources": 0,
            "services": 0,
            "routes": 0,
            "trips": 0,
            "stop_times": 0,
            "sources_reset": 0,
        }

        TimetableDataSource.objects.create(
            name="BHBC",
            url="https://www.buses.co.uk/open-data/network/current",
            active=True,
        )
        TimetableDataSource.objects.create(
            name="Passenger",
            url="https://data.discoverpassenger.com/operator/unilink",
            active=True,
        )
        TimetableDataSource.objects.create(
            name="Ticketer",
            url="https://opendata.ticketer.com/download/example.zip",
            active=True,
        )

        with TemporaryDirectory() as directory:
            with override_settings(DATA_DIR=Path(directory)):
                call_command("refresh_transxchange_sources", all=True)

        self.assertEqual(mock_download.call_count, 1)
        self.assertEqual(mock_import_source.call_count, 1)
