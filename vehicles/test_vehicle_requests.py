from django.contrib.auth.models import Permission
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from unittest.mock import patch

from accounts.models import OperatorUser, User
from busstops.data_changes import apply_pending_change
from busstops.models import DataChangeLog, Operator, Service
from bustimes.models import Garage

from .models import Livery, Vehicle, VehicleRevision


class NewVehicleRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(noc="TEST", name="Test Operator")
        cls.user = User.objects.create_user(
            username="requester",
            email="requester@example.com",
            password="secret",
            trusted=False,  # Default to non-trusted for most tests
        )
        cls.user.user_permissions.add(
            Permission.objects.get(codename="add_vehiclerevision")
        )
        # Create a trusted user for auto-approval tests
        cls.trusted_user = User.objects.create_user(
            username="trusted_requester",
            email="trusted_requester@example.com",
            password="secret",
            trusted=True,
        )
        cls.trusted_user.user_permissions.add(
            Permission.objects.get(codename="add_vehiclerevision")
        )

    def test_operator_fleet_page_links_to_new_vehicle_request(self):
        self.client.force_login(self.user)

        response = self.client.get(self.operator.get_vehicles_url())

        self.assertContains(response, "Request a new vehicle")
        self.assertContains(response, "/operators/test-operator/vehicles/request-new")

    def test_requests_page_lists_request_types(self):
        self.client.force_login(self.user)

        response = self.client.get("/requests")

        self.assertContains(response, "Vehicle")
        self.assertContains(response, "Service")
        self.assertContains(response, "Operator")
        self.assertContains(response, "Vehicle Model")
        self.assertContains(response, "Livery")

    def test_request_new_vehicle_creates_pending_approval(self):
        # Use non-trusted user for this test
        self.client.force_login(self.user)

        response = self.client.post(
            f"/operators/{self.operator.slug}/vehicles/request-new",
            {
                "code": "1234",
                "reg": "YX24 ABC",
                "summary": "Seen working for the operator this week.",
            },
        )

        self.assertContains(response, "sent for approval")

        log = DataChangeLog.objects.get()
        self.assertEqual(log.status, DataChangeLog.STATUS_PENDING)
        self.assertEqual(log.operation, "create")
        self.assertEqual(log.payload["fields"]["operator"], self.operator.pk)
        self.assertEqual(log.payload["fields"]["code"], "1234")
        self.assertEqual(log.payload["fields"]["reg"], "YX24 ABC")

    @override_settings(REQUEST_WEBHOOK_URL="https://discord.example/webhook")
    @patch("accounts.notifications.requests.post")
    def test_vehicle_request_sends_discord_webhook(self, mock_post):
        self.client.force_login(self.user)

        response = self.client.post(
            f"/operators/{self.operator.slug}/vehicles/request-new",
            {
                "code": "1234",
                "reg": "YX24 ABC",
                "summary": "Seen working for the operator this week.",
            },
        )

        self.assertContains(response, "sent for approval")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://discord.example/webhook")
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "New vehicle request")
        self.assertEqual(embed["fields"][0]["value"], "Vehicle")
        self.assertEqual(embed["fields"][1]["value"], "requester (`requester@example.com`)")
        self.assertEqual(embed["fields"][2]["value"], "Test Operator 1234")
        self.assertEqual(embed["fields"][3]["value"], "Seen working for the operator this week.")
        self.assertIn("**Reg:** YX24 ABC", embed["fields"][4]["value"])
        self.assertEqual(embed["url"], "https://bustimes.org/requests")
        self.assertEqual(kwargs["timeout"], 5)

    def test_vehicle_request_shows_in_revisions_feed(self):
        self.client.force_login(self.user)

        self.client.post(
            "/requests/vehicle",
            {
                "operator": self.operator.pk,
                "code": "1234",
                "reg": "YX24 ABC",
                "summary": "Seen working for the operator this week.",
            },
        )

        response = self.client.get("/vehicles/edits?status=pending")

        self.assertContains(response, "Vehicle request")
        self.assertContains(response, "Test Operator 1234")

    def test_trusted_user_vehicle_request_auto_approved(self):
        """Test that vehicle requests from trusted users are automatically approved"""
        self.client.force_login(self.trusted_user)

        response = self.client.post(
            f"/operators/{self.operator.slug}/vehicles/request-new",
            {
                "code": "5678",
                "reg": "YX25 DEF",
                "summary": "Auto-approved trusted user request.",
            },
        )

        # Should not show "sent for approval" since it's auto-approved
        self.assertNotContains(response, "sent for approval")
        
        # Vehicle should be created immediately
        vehicle = Vehicle.objects.get(operator=self.operator, code="5678")
        self.assertEqual(vehicle.reg, "YX25DEF")
        
        # Log should be marked as applied
        log = DataChangeLog.objects.get(target_pk=str(vehicle.id))
        self.assertEqual(log.status, DataChangeLog.STATUS_APPLIED)
        self.assertEqual(log.approved_by, self.trusted_user)

    def test_approved_request_creates_vehicle(self):
        self.client.force_login(self.user)
        self.client.post(
            f"/operators/{self.operator.slug}/vehicles/request-new",
            {
                "code": "1234",
                "reg": "YX24 ABC",
                "summary": "Seen working for the operator this week.",
            },
        )

        log = DataChangeLog.objects.get()
        apply_pending_change(log, user=self.user)

        vehicle = Vehicle.objects.get(operator=self.operator, code="1234")
        self.assertEqual(vehicle.reg, "YX24ABC")

    def test_approved_operator_request_links_to_live_page_from_pending_edits(self):
        self.client.force_login(self.user)
        self.client.post(
            "/requests/operator",
            {
                "noc": "TWO",
                "name": "Second Operator",
                "summary": "Needs adding.",
            },
        )

        log = DataChangeLog.objects.get(source="operator_request")
        apply_pending_change(log, user=self.user)

        response = self.client.get("/vehicles/edits?status=approved")

        self.assertContains(response, "/operators/second-operator")

        approved_operator = Operator.objects.get(noc="TWO")
        approved_response = self.client.get(approved_operator.get_absolute_url())
        self.assertEqual(approved_response.status_code, 200)

    def test_approved_service_request_links_to_live_page_from_pending_edits(self):
        self.client.force_login(self.user)
        self.client.post(
            "/requests/service",
            {
                "operator": self.operator.pk,
                "line_name": "45X",
                "description": "Town - City",
                "service_code": "TEST_45X",
                "summary": "Needs adding.",
            },
        )

        log = DataChangeLog.objects.get(source="service_request")
        apply_pending_change(log, user=self.user)

        response = self.client.get("/vehicles/edits?status=approved")

        approved_service = Service.objects.get(service_code="TEST_45X")
        self.assertContains(response, approved_service.get_absolute_url())

        approved_response = self.client.get(approved_service.get_absolute_url())
        self.assertEqual(approved_response.status_code, 200)

    def test_vehicle_page_links_to_livery_page(self):
        livery = Livery.objects.create(
            name="Test Livery",
            colour="#ffffff",
            colours="#ffffff #003366",
            description="Manually entered livery notes.",
            published=True,
        )
        vehicle = Vehicle.objects.create(
            code="1234",
            operator=self.operator,
            livery=livery,
            reg="YX24ABC",
        )

        response = self.client.get(vehicle.get_absolute_url())

        self.assertContains(response, livery.get_absolute_url())

    def test_vehicle_history_hides_filters_and_shows_entries(self):
        vehicle = Vehicle.objects.create(
            code="1234",
            operator=self.operator,
            reg="YX24ABC",
        )
        VehicleRevision.objects.create(
            vehicle=vehicle,
            changes={"reg": "-YX24ABC\n+YX24ABD"},
            message="Corrected registration",
            created_at=timezone.now(),
            pending=False,
            disapproved=False,
        )

        response = self.client.get(f"/vehicles/edits?vehicle={vehicle.id}&status=approved")

        self.assertContains(response, f"<h1>{vehicle} history</h1>", html=True)
        self.assertContains(response, "Corrected registration")
        self.assertNotContains(response, "Apply filters")

    def test_vehicle_page_history_link_uses_full_approved_filter_query(self):
        vehicle = Vehicle.objects.create(
            code="35115",
            operator=self.operator,
            reg="YX24ABC",
        )

        response = self.client.get(vehicle.get_absolute_url())

        self.assertContains(
            response,
            f'/vehicles/edits?show=all&amp;q=&amp;operator=&amp;vehicle={vehicle.id}&amp;user=&amp;status=approved',
        )

    def test_livery_page_shows_manual_details(self):
        livery = Livery.objects.create(
            name="Test Livery",
            colour="#ffffff",
            colours="#ffffff #003366",
            description="Manually entered livery notes.",
            published=True,
        )

        response = self.client.get(livery.get_absolute_url())

        self.assertContains(response, "Test Livery")
        self.assertContains(response, "Manually entered livery notes.")

    def test_vehicle_edit_request_can_change_garage(self):
        garage_a = Garage.objects.create(code="GAR1", name="Garage One", operator=self.operator)
        garage_b = Garage.objects.create(code="GAR2", name="Garage Two", operator=self.operator)
        vehicle = Vehicle.objects.create(
            code="1234",
            operator=self.operator,
            reg="YX24ABC",
            garage=garage_a,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            vehicle.get_edit_url(),
            {
                "fleet_number": "",
                "reg": vehicle.reg,
                "operator": self.operator.pk,
                "garage": garage_b.pk,
                "vehicle_type": "",
                "colours": "",
                "other_colour": "",
                "branding": "",
                "rear_advert": "",
                "name": "",
                "previous_reg": "",
                "notes": "",
                "summary": "Moved to the other garage.",
            },
        )

        revision = VehicleRevision.objects.get(vehicle=vehicle)

        self.assertContains(response, "Your changes")
        self.assertEqual(revision.from_garage, garage_a)
        self.assertEqual(revision.to_garage, garage_b)
        self.assertTrue(revision.pending)

    def test_non_local_expert_can_still_edit_operator_vehicle(self):
        vehicle = Vehicle.objects.create(
            code="1234",
            operator=self.operator,
            reg="YX24ABC",
        )
        local_expert = User.objects.create_user(
            username="expert",
            email="expert@example.com",
            password="secret",
        )
        OperatorUser.objects.create(operator=self.operator, user=local_expert)

        self.client.force_login(self.user)

        response = self.client.get(vehicle.get_edit_url())

        self.assertEqual(response.status_code, 200)
