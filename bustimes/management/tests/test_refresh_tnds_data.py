from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from busstops.models import DataSource, Region, Service
from bustimes.models import Route


class RefreshTNDSDataTests(TestCase):
    @mock.patch("bustimes.management.commands.refresh_tnds_data.call_command")
    def test_refresh_tnds_data_replaces_tnds_only(self, mock_call_command):
        region = Region.objects.create(pk="N", name="North")
        tnds_source = DataSource.objects.create(
            name="EA",
            url="ftp://ftp.tnds.basemap.co.uk/EA.zip",
            sha1="old-tnds",
        )
        other_source = DataSource.objects.create(
            name="BODS",
            url="https://data.bus-data.dft.gov.uk/dataset/1",
            sha1="other",
        )

        tnds_service = Service.objects.create(
            service_code="ea-1",
            line_name="1",
            region=region,
            source=tnds_source,
        )
        other_service = Service.objects.create(
            service_code="bod-1",
            line_name="2",
            region=region,
            source=other_source,
        )

        Route.objects.create(service=tnds_service, source=tnds_source, line_name="1")
        Route.objects.create(service=other_service, source=other_source, line_name="2")

        with TemporaryDirectory() as directory:
            archive_path = Path(directory) / "EA.zip"
            archive_path.write_bytes(b"old archive")

            with override_settings(TNDS_DIR=Path(directory)):
                call_command("refresh_tnds_data", "user", "pass")

            self.assertFalse(archive_path.exists())

        tnds_source.refresh_from_db()
        other_source.refresh_from_db()

        self.assertFalse(Service.objects.filter(pk=tnds_service.pk).exists())
        self.assertTrue(Service.objects.filter(pk=other_service.pk).exists())
        self.assertEqual(tnds_source.sha1, None)
        self.assertEqual(other_source.sha1, "other")
        self.assertEqual(
            mock_call_command.call_args_list,
            [mock.call("import_tnds", "user", "pass")],
        )

    @mock.patch("bustimes.management.commands.refresh_tnds_data.call_command")
    def test_refresh_tnds_data_can_keep_archives(self, mock_call_command):
        with TemporaryDirectory() as directory:
            archive_path = Path(directory) / "EA.zip"
            archive_path.write_bytes(b"old archive")

            with override_settings(TNDS_DIR=Path(directory)):
                call_command("refresh_tnds_data", "user", "pass", keep_archives=True)

            self.assertTrue(archive_path.exists())
        self.assertEqual(
            mock_call_command.call_args_list,
            [mock.call("import_tnds", "user", "pass")],
        )
