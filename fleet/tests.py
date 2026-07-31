from __future__ import annotations

from unittest.mock import patch

from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import User
from bustimes.models import Garage
from busstops.models import Operator
from fleet.completion import get_user_ride_stats
from fleet.discord_bot import execute_check_command, execute_log_command
from fleet.exporters.xlsx import build_fleet_workbook
from fleet.live_import import build_import_rows, commit_import_rows
from fleet.matching import match_garage, match_operator
from fleet.models import FleetPDFUpload, FleetRideLog, FleetVehicle
from fleet.parsers.pdf_fleet_parser import TARGET_COLUMNS, parse_text_pages
from vehicles.models import Vehicle, VehicleType


@override_settings(MEDIA_ROOT="C:/tmp/betterfleet-test-media")
class FleetParserTests(TestCase):
    def test_parse_sample_text_block(self):
        sample_page = """
        Chassis Type: Volvo B11R  Body Type: Plaxton Elite
        Fleet No  Reg No  Layout  New  Depot  Livery
        1  HF17AZA  C51FT  2017  Pimperne  Damory
        2  HF17AZB  C51FT  2017  Pimperne  Damory
        3  HF17AZC  C51FT  2017  Coach Unit  Excelsior

        Named Vehicles:
        1 - Coast Rider
        Branding:
        3 - Luxury Coach
        Previous Registrations:
        2 - AB12CDE
        Previous Owners:
        3 - National Express
        """

        records = parse_text_pages([sample_page])

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].operator_code, "EXLS")
        self.assertEqual(records[0].fleet_number, "1")
        self.assertEqual(records[0].fleet_code, "1")
        self.assertEqual(records[0].code, "1")
        self.assertEqual(records[0].registration, "HF17AZA")
        self.assertEqual(records[0].vehicle_type, "Volvo B11R Plaxton Elite")
        self.assertEqual(records[0].garage, "GSC Pimperne")
        self.assertEqual(records[0].livery, "Damory")
        self.assertEqual(records[0].name, "Coast Rider")
        self.assertEqual(records[1].prev_registration, "AB12CDE")
        self.assertEqual(records[2].branding, "Luxury Coach")
        self.assertIn("Previous owner: National Express", records[2].notes)


class FleetExportTests(TestCase):
    def test_xlsx_export_headers_match_target_columns(self):
        upload = FleetPDFUpload.objects.create(
            file=SimpleUploadedFile("gsc.pdf", b"%PDF-1.4"),
            original_filename="gsc.pdf",
        )
        vehicle = FleetVehicle.objects.create(
            source_pdf=upload,
            operator_code="EXLS",
            code="1",
            fleet_number="1",
            fleet_code="1",
            registration="HF17AZA",
            vehicle_type="Volvo B11R Plaxton Elite",
            livery="Damory",
            garage="GSC Pimperne",
        )

        workbook = build_fleet_workbook([vehicle])
        headers = [cell.value for cell in workbook.active[1]]

        self.assertEqual(headers, list(TARGET_COLUMNS))


class FleetMatchingTests(TestCase):
    def test_operator_and_depot_matching_preview(self):
        operator = Operator.objects.create(noc="EXLS", name="Excelsior", slug="excelsior")
        Garage.objects.create(operator=operator, code="PIM", name="Pimperne")

        operator_preview = match_operator("EXLS")
        garage_preview = match_garage("GSC Pimperne", "EXLS")
        missing_garage_preview = match_garage("GSC Coach Unit", "EXLS")

        self.assertTrue(operator_preview.is_match)
        self.assertIn("Match EXLS - Excelsior", operator_preview.label)
        self.assertTrue(garage_preview.is_match)
        self.assertIn("Match depot Pimperne", garage_preview.label)
        self.assertEqual(missing_garage_preview.action, "create")
        self.assertIn("Create depot GSC Coach Unit for EXLS", missing_garage_preview.label)


class FleetLiveImportTests(TestCase):
    def test_build_and_commit_live_import_rows(self):
        operator = Operator.objects.create(noc="EXLS", name="Excelsior", slug="excelsior")
        Garage.objects.create(operator=operator, code="Pimperne", name="Pimperne")
        upload = FleetPDFUpload.objects.create(
            file=SimpleUploadedFile("gsc.pdf", b"%PDF-1.4"),
            original_filename="gsc.pdf",
        )
        FleetVehicle.objects.create(
            source_pdf=upload,
            operator_code="EXLS",
            code="1",
            fleet_number="1",
            fleet_code="1",
            registration="HF17AZA",
            vehicle_type="Volvo B11R Plaxton Elite",
            livery="Damory",
            garage="GSC Pimperne",
            name="Coast Rider",
        )

        rows = build_import_rows(upload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operator_preview"].action, "match")
        self.assertEqual(rows[0]["garage_preview"].action, "match")

        summary = commit_import_rows(rows)
        self.assertEqual(summary.created, 1)
        self.assertEqual(summary.updated, 0)

        vehicle = Vehicle.objects.get(operator=operator, code="1")
        self.assertEqual(vehicle.reg, "HF17AZA")
        self.assertEqual(vehicle.garage.name, "Pimperne")


@override_settings(MEDIA_ROOT="C:/tmp/betterfleet-test-media")
class FleetAdminActionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="pass",
        )

    def test_process_selected_pdfs_admin_action(self):
        upload = FleetPDFUpload.objects.create(
            file=SimpleUploadedFile("gsc.pdf", b"%PDF-1.4"),
            original_filename="gsc.pdf",
        )

        parsed_row = {
            "operator_code": "EXLS",
            "external_id": "",
            "code": "1",
            "fleet_number": "1",
            "fleet_code": "1",
            "registration": "HF17AZA",
            "prev_registration": "",
            "vehicle_type": "Volvo B11R Plaxton Elite",
            "livery": "Damory",
            "colours": "",
            "garage": "GSC Pimperne",
            "name": "",
            "branding": "",
            "notes": "",
            "withdrawn": False,
            "preserved": False,
            "fleet_support_vehicle": False,
            "vor": False,
            "awaiting_delivery": False,
            "trainer_vehicle": False,
            "demonstrator": False,
            "source_page": 1,
            "raw_text": "1 HF17AZA C51FT 2017 Pimperne Damory",
        }

        self.client.force_login(self.superuser)
        with patch("fleet.services.parse_pdf") as mocked_parse_pdf:
            from fleet.parsers.pdf_fleet_parser import ParsedFleetRecord

            mocked_parse_pdf.return_value = [ParsedFleetRecord(**parsed_row)]
            response = self.client.post(
                "/admin/fleet/fleetpdfupload/",
                {
                    "action": "process_selected_pdfs",
                    ACTION_CHECKBOX_NAME: [upload.pk],
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        upload.refresh_from_db()
        self.assertEqual(upload.status, FleetPDFUpload.Status.COMPLETED)
        self.assertEqual(upload.vehicles.count(), 1)
        vehicle = upload.vehicles.get()
        self.assertEqual(vehicle.registration, "HF17AZA")


class FleetCompletionFeatureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.permission = Permission.objects.get(codename="use_beta_features")
        cls.operator = Operator.objects.create(noc="TEST", name="Test Operator", slug="test-operator")
        cls.other_operator = Operator.objects.create(noc="OTHR", name="Other Operator", slug="other-operator")
        cls.vehicle_type = VehicleType.objects.create(name="Enviro 400")
        cls.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="secret",
            discord_user_id="12345",
        )
        cls.viewer.user_permissions.add(cls.permission)
        cls.public_user = User.objects.create_user(
            username="public-rider",
            email="public@example.com",
            password="secret",
            fleet_logging_public=True,
        )
        cls.public_user.user_permissions.add(cls.permission)
        cls.private_user = User.objects.create_user(
            username="private-rider",
            email="private@example.com",
            password="secret",
            fleet_logging_public=False,
        )
        cls.private_user.user_permissions.add(cls.permission)
        cls.vehicle_one = Vehicle.objects.create(
            code="BUS1",
            fleet_code="1001",
            fleet_number=1001,
            reg="YX24ABC",
            operator=cls.operator,
            vehicle_type=cls.vehicle_type,
        )
        cls.vehicle_two = Vehicle.objects.create(
            code="BUS2",
            fleet_code="1002",
            fleet_number=1002,
            reg="YX24ABD",
            operator=cls.operator,
            vehicle_type=cls.vehicle_type,
            trainer_vehicle=True,
        )
        cls.vehicle_three = Vehicle.objects.create(
            code="COACH1",
            fleet_code="1001",
            fleet_number=1001,
            reg="YX24ZZZ",
            operator=cls.other_operator,
            vehicle_type=cls.vehicle_type,
        )

    def test_ride_log_is_unique_per_user_and_vehicle(self):
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)
        with self.assertRaises(Exception):
            FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)
        FleetRideLog.objects.create(user=self.public_user, vehicle=self.vehicle_one)
        self.assertEqual(FleetRideLog.objects.filter(vehicle=self.vehicle_one).count(), 2)

    def test_operator_page_hides_completion_without_permission(self):
        no_permission_user = User.objects.create_user(
            username="plain",
            email="plain@example.com",
            password="secret",
        )
        self.client.force_login(no_permission_user)

        response = self.client.get(self.operator.get_vehicles_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Fleet completion:")
        self.assertNotContains(response, "Ridden")

    def test_operator_page_shows_completion_with_permission(self):
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)
        self.client.force_login(self.viewer)

        response = self.client.get(self.operator.get_vehicles_url())

        self.assertContains(response, "Fleet completion:")
        self.assertContains(response, "1/1")
        self.assertContains(response, "Ridden")
        self.assertContains(response, "✓")
        self.assertContains(response, ">-<")
        self.assertContains(response, "Mass log vehicles")

    def test_operator_page_mass_log_mode_shows_checkboxes_and_saves(self):
        self.client.force_login(self.viewer)

        response = self.client.get(f"{self.operator.get_vehicles_url()}?mass_log=1")
        self.assertContains(response, 'name="logged_vehicle_ids"')
        self.assertContains(response, "Save ride logs")

        response = self.client.post(
            f"{self.operator.get_vehicles_url()}?mass_log=1",
            {
                "mass_log_save": "1",
                "logged_vehicle_ids": [str(self.vehicle_one.pk), str(self.vehicle_two.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FleetRideLog.objects.filter(user=self.viewer).count(), 2)

    def test_operator_page_can_toggle_dvla_tax_and_euro_status_columns(self):
        self.vehicle_one.dvla_tax_status = "SORN"
        self.vehicle_one.dvla_euro_status = "EURO 6 AD"
        self.vehicle_one.save(update_fields=["dvla_tax_status", "dvla_euro_status"])

        response = self.client.get(self.operator.get_vehicles_url())
        self.assertContains(response, "Show DVLA tax and euro status")
        self.assertNotContains(
            response,
            '<th scope="col" class="trivia">Tax status</th>',
            html=False,
        )

        response = self.client.get(f"{self.operator.get_vehicles_url()}?show_dvla_status=1")
        self.assertContains(response, "Hide DVLA tax and euro status")
        self.assertContains(response, "Tax status")
        self.assertContains(response, "Euro status")
        self.assertContains(response, "SORN")
        self.assertContains(response, "EURO 6 AD")

    def test_vehicle_detail_page_shows_log_button_and_can_toggle(self):
        self.client.force_login(self.viewer)

        response = self.client.get(self.vehicle_one.get_absolute_url())
        self.assertContains(response, "Mark as logged")

        response = self.client.post(
            self.vehicle_one.get_absolute_url(),
            {"toggle_ride_log": "1"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(FleetRideLog.objects.filter(user=self.viewer, vehicle=self.vehicle_one).exists())

        response = self.client.get(self.vehicle_one.get_absolute_url())
        self.assertContains(response, "Unlog vehicle")

    def test_profile_stats_follow_visibility_rules(self):
        FleetRideLog.objects.create(user=self.public_user, vehicle=self.vehicle_one)
        FleetRideLog.objects.create(user=self.public_user, vehicle=self.vehicle_two)
        self.client.force_login(self.viewer)

        response = self.client.get(self.public_user.get_absolute_url())
        self.assertContains(response, "vehicles ridden")
        self.assertContains(response, "66.7% completion")

        response = self.client.get(self.private_user.get_absolute_url())
        self.assertNotContains(response, "vehicles ridden")

    def test_completion_page_requires_permission(self):
        self.client.force_login(self.viewer)
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)
        FleetRideLog.objects.create(user=self.public_user, vehicle=self.vehicle_two)

        response = self.client.get("/fleet/completion")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your most logged operators")
        self.assertContains(response, "Overall most logged operators")

        no_permission_user = User.objects.create_user(
            username="noperms",
            email="noperms@example.com",
            password="secret",
        )
        self.client.force_login(no_permission_user)
        response = self.client.get("/fleet/completion")
        self.assertEqual(response.status_code, 403)

    def test_admin_mass_log_action_is_idempotent(self):
        superuser = User.objects.create_superuser(
            username="root2",
            email="root2@example.com",
            password="pass",
        )
        self.client.force_login(superuser)
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)

        response = self.client.post(
            "/admin/vehicles/vehicle/",
            {
                "action": "mass_log_vehicles",
                ACTION_CHECKBOX_NAME: [self.vehicle_one.pk, self.vehicle_two.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            "/admin/vehicles/vehicle/",
            {
                "action": "mass_log_vehicles",
                ACTION_CHECKBOX_NAME: [self.vehicle_one.pk, self.vehicle_two.pk],
                "apply": "1",
                "user": self.viewer.pk,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FleetRideLog.objects.filter(user=self.viewer).count(), 2)

    def test_user_ride_stats_counts_vehicles_operators_and_types(self):
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_three)

        stats = get_user_ride_stats(self.viewer)

        self.assertEqual(stats["vehicles"], 2)
        self.assertEqual(stats["operators"], 2)
        self.assertEqual(stats["types"], 1)

    def test_logged_trainer_and_vor_vehicles_are_included_in_completion_counts(self):
        self.vehicle_three.vor = True
        self.vehicle_three.save(update_fields=["vor"])
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_two)
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_three)

        stats = get_user_ride_stats(self.viewer)

        self.assertEqual(stats["vehicles"], 3)
        self.assertEqual(stats["operators"], 2)
        self.assertEqual(stats["types"], 1)

    def test_unlogged_trainer_vor_and_fleet_support_vehicles_are_excluded_from_totals(self):
        self.vehicle_three.vor = True
        self.vehicle_three.fleet_support_vehicle = True
        self.vehicle_three.save(update_fields=["vor", "fleet_support_vehicle"])
        FleetRideLog.objects.create(user=self.viewer, vehicle=self.vehicle_one)

        stats = get_user_ride_stats(self.viewer)

        self.assertEqual(stats["vehicles"], 1)
        self.assertEqual(stats["operators"], 1)
        self.assertEqual(stats["types"], 1)

    def test_discord_log_and_check_commands(self):
        result = execute_check_command("99999", "1001")
        self.assertEqual(result.status, "forbidden")

        no_permission_user = User.objects.create_user(
            username="discordless",
            email="discordless@example.com",
            password="secret",
            discord_user_id="22222",
        )
        result = execute_log_command("22222", "1001")
        self.assertEqual(result.status, "forbidden")

        result = execute_log_command("12345", "YX24ABC")
        self.assertEqual(result.status, "created")
        self.assertTrue(FleetRideLog.objects.filter(user=self.viewer, vehicle=self.vehicle_one).exists())

        result = execute_log_command("12345", "YX24ABC")
        self.assertEqual(result.status, "duplicate")

        result = execute_check_command("12345", "YX24ABC")
        self.assertEqual(result.status, "logged")

    def test_discord_command_reports_multiple_matches(self):
        result = execute_log_command("12345", "1001")
        self.assertEqual(result.status, "multiple")
        self.assertEqual(len(result.matches), 2)

        result = execute_log_command("12345", "1001", noc="TEST")
        self.assertEqual(result.status, "created")
