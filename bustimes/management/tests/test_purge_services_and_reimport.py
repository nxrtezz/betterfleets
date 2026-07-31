from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from busstops.models import DataSource, Service
from bustimes.models import Route


class PurgeServicesAndReimportTests(TestCase):
    def test_requires_reimport_inputs_unless_skipped(self):
        with self.assertRaisesMessage(
            CommandError,
            "Pass --bod-api-key and/or TNDS credentials to reimport, or pass --skip-reimport to purge only.",
        ):
            call_command(
                "purge_services_and_reimport",
                apply=True,
                yes_delete_services=True,
            )

    def test_requires_complete_tnds_credentials(self):
        with self.assertRaisesMessage(
            CommandError,
            "Pass both --tnds-username and --tnds-password to reimport TNDS.",
        ):
            call_command(
                "purge_services_and_reimport",
                apply=True,
                yes_delete_services=True,
                tnds_username="user",
            )

    @mock.patch("bustimes.management.commands.purge_services_and_reimport.call_command")
    def test_reimports_bods_and_tnds_and_resets_tnds_sources(self, mock_call_command):
        service_source = DataSource.objects.create(source="txc", url="https://source.test")
        Service.objects.create(service_code="S1", line_name="1", source=service_source)
        Route.objects.create(source=service_source, line_name="1")
        bod_source = DataSource.objects.create(
            source="txc",
            url="https://data.bus-data.dft.gov.uk/dataset/1",
            sha1="bod",
        )
        tnds_source = DataSource.objects.create(
            source="txc",
            url="ftp://ftp.tnds.basemap.co.uk/EA.zip",
            sha1="tnds",
        )

        call_command(
            "purge_services_and_reimport",
            apply=True,
            yes_delete_services=True,
            bod_api_key="x" * 40,
            tnds_username="user",
            tnds_password="pass",
        )

        bod_source.refresh_from_db()
        tnds_source.refresh_from_db()

        self.assertEqual(bod_source.sha1, None)
        self.assertEqual(tnds_source.sha1, None)
        self.assertFalse(Service.objects.exists())
        self.assertFalse(Route.objects.exists())
        self.assertEqual(
            mock_call_command.call_args_list,
            [
                mock.call("import_timetable_data", "bod", "x" * 40),
                mock.call("import_tnds", "user", "pass"),
            ],
        )
