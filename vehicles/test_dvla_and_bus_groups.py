from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from busstops.models import Operator, OperatorGroup, Organisation, PreservationGroup

from .models import BusGroup, Vehicle, VehicleType


class PreservationOwnershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(username="preserver")
        cls.group = PreservationGroup.objects.create(
            name="Test Preservation Group",
            slug="test-preservation-group",
        )

    def test_vehicle_can_be_preserved_by_user(self):
        vehicle = Vehicle.objects.create(
            code="PRESUSER",
            preserved=True,
            preserved_by_user=self.user,
        )

        self.assertEqual(vehicle.preservation_owner, self.user)

    def test_vehicle_can_be_preserved_by_group(self):
        vehicle = Vehicle.objects.create(
            code="PRESGROUP",
            preserved=True,
            preservation_group=self.group,
        )

        self.assertEqual(vehicle.preservation_owner, self.group)

    def test_vehicle_rejects_two_preservation_owners_in_python(self):
        vehicle = Vehicle(
            code="PRESDOUBLE",
            preserved=True,
            preserved_by_user=self.user,
            preservation_group=self.group,
        )

        with self.assertRaises(ValidationError):
            vehicle.full_clean()

    def test_vehicle_rejects_two_preservation_owners_in_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vehicle.objects.create(
                    code="PREDBDOUBLE",
                    preserved=True,
                    preserved_by_user=self.user,
                    preservation_group=self.group,
                )


class ImportDvlaCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(noc="TEST", name="Test Operator", slug="test-operator")
        cls.other_operator = Operator.objects.create(
            noc="OTHR",
            name="Other Operator",
            slug="other-operator",
        )
        cls.organisation = Organisation.objects.create(
            slug="test-org",
            name="Test Organisation",
        )
        cls.operator_group = OperatorGroup.objects.create(
            slug="test-group",
            name="Test Group",
            organisation=cls.organisation,
        )
        cls.operator.organisation = cls.organisation
        cls.operator.group = cls.operator_group
        cls.operator.save(update_fields=["organisation", "group"])
        cls.vehicle = Vehicle.objects.create(
            code="BUS1",
            fleet_code="1001",
            reg="YX24ABC",
            operator=cls.operator,
        )
        cls.no_reg_vehicle = Vehicle.objects.create(
            code="BUS2",
            fleet_code="1002",
            operator=cls.operator,
        )
        cls.other_vehicle = Vehicle.objects.create(
            code="BUS3",
            fleet_code="1003",
            reg="YX24ABD",
            operator=cls.other_operator,
        )

    @patch("vehicles.management.commands.import_dvla.fetch_dvla_record")
    @patch("builtins.input", return_value="n")
    def test_import_dvla_previews_and_skips_apply_when_denied(self, _mock_input, mock_fetch):
        mock_fetch.return_value = {
            "taxStatus": "Taxed",
            "motStatus": "Valid",
            "euroStatus": "EURO 6",
        }
        stdout = StringIO()

        call_command(
            "import_dvla",
            "--operator",
            "TEST",
            "--api_key",
            "test-key",
            stdout=stdout,
        )

        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.dvla_tax_status, "")
        self.assertEqual(self.vehicle.dvla_mot_status, "")
        self.assertEqual(self.vehicle.dvla_euro_status, "")
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertIn("DVLA preview for TEST - Test Operator", stdout.getvalue())
        self.assertIn("Cancelled. No DVLA data was applied.", stdout.getvalue())

    @patch("vehicles.management.commands.import_dvla.fetch_dvla_record")
    def test_import_dvla_apply_updates_target_operator(self, mock_fetch):
        mock_fetch.return_value = {
            "taxStatus": "SORN",
            "motStatus": "Not valid",
            "euroStatus": "EURO 6 AD",
        }
        stdout = StringIO()

        call_command(
            "import_dvla",
            "--operator",
            "TEST",
            "--api_key",
            "test-key",
            "--apply",
            stdout=stdout,
        )

        self.vehicle.refresh_from_db()
        self.no_reg_vehicle.refresh_from_db()
        self.other_vehicle.refresh_from_db()

        self.assertEqual(self.vehicle.dvla_tax_status, "SORN")
        self.assertEqual(self.vehicle.dvla_mot_status, "Not valid")
        self.assertEqual(self.vehicle.dvla_euro_status, "EURO 6 AD")
        self.assertIsNotNone(self.vehicle.dvla_tax_status_checked_at)
        self.assertEqual(self.no_reg_vehicle.dvla_tax_status, "")
        self.assertEqual(self.no_reg_vehicle.dvla_mot_status, "")
        self.assertEqual(self.other_vehicle.dvla_tax_status, "")
        self.assertEqual(self.other_vehicle.dvla_mot_status, "")
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertIn("Applied DVLA data to 1 vehicle(s).", stdout.getvalue())

    @patch("vehicles.management.commands.import_dvla.fetch_dvla_record")
    def test_import_dvla_apply_updates_target_organisation(self, mock_fetch):
        mock_fetch.return_value = {
            "taxStatus": "Taxed",
            "motStatus": "Valid",
            "euroStatus": "EURO 5",
        }
        stdout = StringIO()

        call_command(
            "import_dvla",
            "--organisation",
            "test-org",
            "--api_key",
            "test-key",
            "--apply",
            stdout=stdout,
        )

        self.vehicle.refresh_from_db()
        self.other_vehicle.refresh_from_db()

        self.assertEqual(self.vehicle.dvla_tax_status, "Taxed")
        self.assertEqual(self.vehicle.dvla_mot_status, "Valid")
        self.assertEqual(self.other_vehicle.dvla_tax_status, "")
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertIn("DVLA preview for organisation test-org - Test Organisation", stdout.getvalue())

    @patch("vehicles.management.commands.import_dvla.fetch_dvla_record")
    def test_import_dvla_apply_updates_target_operator_group(self, mock_fetch):
        mock_fetch.return_value = {
            "taxStatus": "Untaxed",
            "motStatus": "No details held by DVLA",
            "euroStatus": "EURO 4",
        }
        stdout = StringIO()

        call_command(
            "import_dvla",
            "--operator-group",
            "test-group",
            "--api_key",
            "test-key",
            "--apply",
            stdout=stdout,
        )

        self.vehicle.refresh_from_db()
        self.other_vehicle.refresh_from_db()

        self.assertEqual(self.vehicle.dvla_tax_status, "Untaxed")
        self.assertEqual(self.vehicle.dvla_mot_status, "No details held by DVLA")
        self.assertEqual(self.other_vehicle.dvla_tax_status, "")
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertIn("DVLA preview for operator group test-group - Test Group", stdout.getvalue())


class BusGroupViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bus_group = BusGroup.objects.create(
            title="Pride Buses",
            slug="pride-buses",
            description="Rainbow liveries across the fleet.",
            header_background="#112233",
            header_foreground="#ffffff",
            accent_colour="#ff006e",
            event_date="2026-08-29",
            event_end_date="2026-08-30",
        )

    def test_bus_group_page_displays_basic_info(self):
        response = self.client.get(self.bus_group.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pride Buses")
        self.assertContains(response, "Rainbow liveries across the fleet.")
        self.assertContains(response, "2026-08-29")
        self.assertContains(response, "2026-08-30")

    def test_events_page_displays_bus_groups(self):
        response = self.client.get("/events")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pride Buses")
        self.assertContains(response, "2026-08-29")

    def test_events_page_search_filters_bus_groups(self):
        response = self.client.get("/events?search=pride")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pride Buses")

    def test_events_page_search_no_results(self):
        response = self.client.get("/events?search=nonexistent")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No events found")
