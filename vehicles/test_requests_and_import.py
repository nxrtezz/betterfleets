from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from busstops.models import DataSource, Operator
from bustimes.models import Garage

from .historical_fleet_bulk_import import COLUMN_KEYS
from .models import Livery, Vehicle, VehicleType


class RequestsAndImportViewsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.superuser = self.user_model.objects.create_superuser(
            email="admin@example.com",
            username="admin",
            password="password123",
        )
        self.source = DataSource.objects.create(name="Manual")
        self.operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator",
            source=self.source,
            vehicle_mode="bus",
        )

    def _row_text(self, *values):
        header = "\t".join(COLUMN_KEYS)
        row = "\t".join(values)
        return f"{header}\n{row}"

    # AdditionRequest model was removed - these tests are no longer functional
    # def test_authenticated_user_can_submit_livery_request(self):
    #     self.client.login(email="user@example.com", password="password123")
    #
    #     response = self.client.post(
    #         reverse("addition_request_page", args=(AdditionRequestType.LIVERY,)),
    #         {
    #             "name": "New Blue",
    #             "colour": "#0055aa",
    #             "colours": "#0055aa #ffffff",
    #         },
    #         follow=True,
    #     )
    #
    #     self.assertEqual(response.status_code, 200)
    #     addition_request = AdditionRequest.objects.get()
    #     self.assertEqual(addition_request.request_type, AdditionRequestType.LIVERY)
    #     self.assertEqual(addition_request.status, AdditionRequestStatus.PENDING)
    #     self.assertEqual(addition_request.requested_by, self.user)
    #     self.assertEqual(addition_request.data["name"], "New Blue")
    #
    # def test_superuser_can_approve_livery_request(self):
    #     addition_request = AdditionRequest.objects.create(
    #         request_type=AdditionRequestType.LIVERY,
    #         requested_by=self.user,
    #         data={"name": "Approval Blue", "colour": "#003399", "colours": "#003399 #ffffff"},
    #     )
    #     self.client.login(email="admin@example.com", password="password123")
    #
    #     response = self.client.post(
    #         reverse("addition_request_review"),
    #         {"request_id": addition_request.pk, "action": "approve"},
    #         follow=True,
    #     )
    #
    #     self.assertEqual(response.status_code, 200)
    #     addition_request.refresh_from_db()
    #     self.assertEqual(addition_request.status, AdditionRequestStatus.APPROVED)
    #     self.assertTrue(Livery.objects.filter(name="Approval Blue", published=True).exists())

    def test_live_fleet_mass_import_reports_missing_records_with_admin_links(self):
        self.client.login(email="admin@example.com", password="password123")
        bulk_text = self._row_text(
            "101",
            "101",
            "AB12CDE",
            "101",
            "Brand",
            "Bus Name",
            "",
            "Missing Type",
            "Missing Livery",
            "#ffffff #0000ff",
            "Missing Garage",
        )

        response = self.client.post(
            reverse("live_fleet_mass_import"),
            {"operator": self.operator.pk, "bulk_text": bulk_text},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Line 1: Livery 'Missing Livery' not found.")
        self.assertContains(response, "/admin/vehicles/livery/add/?name=Missing+Livery")
        self.assertContains(response, "/admin/vehicles/vehicletype/add/?name=Missing+Type")
        self.assertContains(response, f"/admin/bustimes/garage/add/?name=Missing+Garage&amp;code=Missing+Garage&amp;operator={self.operator.pk}")
        self.assertFalse(Vehicle.objects.filter(operator=self.operator, code="101").exists())

    def test_live_fleet_mass_import_creates_vehicle_when_refs_exist(self):
        self.client.login(email="admin@example.com", password="password123")
        livery = Livery.objects.create(
            name="Fleet Blue",
            colour="#003399",
            colours="#003399 #ffffff",
            published=True,
        )
        vehicle_type = VehicleType.objects.create(name="Enviro400")
        garage = Garage.objects.create(operator=self.operator, code="GK", name="Garage King")
        bulk_text = self._row_text(
            "202",
            "202",
            "XY12ZZZ",
            "202",
            "Brand",
            "Bus Name",
            "Nice bus",
            vehicle_type.name,
            livery.name,
            "#003399 #ffffff",
            garage.name,
        )

        response = self.client.post(
            reverse("live_fleet_mass_import"),
            {"operator": self.operator.pk, "bulk_text": bulk_text},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        vehicle = Vehicle.objects.get(operator=self.operator, code="202", historical_fleet__isnull=True)
        self.assertEqual(vehicle.livery_id, livery.id)
        self.assertEqual(vehicle.vehicle_type_id, vehicle_type.id)
        self.assertEqual(vehicle.garage_id, garage.id)
        self.assertTrue(vehicle.is_manual)
