from io import StringIO
from urllib.parse import urlparse
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from busstops.models import Operator
from vehicles.models import Livery, Vehicle, VehicleType


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@override_settings(BUSTIMES_API_BASE_URL="https://api.example.test")
class RepairVehicleLiveriesTests(TestCase):
    def test_repair_vehicle_liveries_backfills_missing_livery_from_api(self):
        operator = Operator.objects.create(
            noc="OPL", name="Livery Operator", slug="livery-operator"
        )
        livery = Livery.objects.create(
            name="Demo Livery", colour="#ff0000", external_id="liv-1"
        )
        vehicle = Vehicle.objects.create(operator=operator, code="300")

        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/vehicles/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "veh-liv-1",
                            "operator": "OPL",
                            "code": "300",
                            "livery": "liv-1",
                        }
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            side_effect=fake_get,
        ):
            call_command("repair_vehicle_liveries")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.livery, livery)

    def test_repair_vehicle_liveries_matches_existing_livery_by_api_name(self):
        operator = Operator.objects.create(
            noc="OPN", name="Named Operator", slug="named-operator"
        )
        livery = Livery.objects.create(name="Named Livery", colour="#112233")
        vehicle = Vehicle.objects.create(operator=operator, code="400")

        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/vehicles/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "veh-name-1",
                            "operator": "OPN",
                            "code": "400",
                            "livery": {"id": "api-liv-99", "name": "Named Livery"},
                        }
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            side_effect=fake_get,
        ), patch(
            "vehicles.management.commands.repair_vehicle_liveries.call_command"
        ) as mocked_call_command:
            call_command("repair_vehicle_liveries")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.livery, livery)
        mocked_call_command.assert_not_called()

    def test_repair_vehicle_liveries_infers_from_operator_and_vehicle_type(self):
        operator = Operator.objects.create(
            noc="OPT", name="Pattern Operator", slug="pattern-operator"
        )
        vehicle_type = VehicleType.objects.create(name="Enviro400")
        livery = Livery.objects.create(name="Fleet Livery", colour="#00aa00")
        Vehicle.objects.create(
            operator=operator,
            code="100",
            vehicle_type=vehicle_type,
            livery=livery,
        )
        vehicle = Vehicle.objects.create(
            operator=operator,
            code="101",
            vehicle_type=vehicle_type,
        )

        with patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            return_value=FakeResponse(200, []),
        ):
            call_command("repair_vehicle_liveries")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.livery, livery)

    def test_repair_vehicle_liveries_is_idempotent_and_reports_summary(self):
        operator = Operator.objects.create(
            noc="OPC", name="Colour Operator", slug="colour-operator"
        )
        livery = Livery.objects.create(
            name="Colour Match", colour="#123456", colours="#123456 #abcdef"
        )
        vehicle = Vehicle.objects.create(
            operator=operator,
            code="200",
            colours="#123456 #abcdef",
        )

        first_output = StringIO()
        second_output = StringIO()

        with patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            return_value=FakeResponse(200, []),
        ):
            call_command("repair_vehicle_liveries", stdout=first_output)
            call_command("repair_vehicle_liveries", stdout=second_output)

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.livery, livery)
        self.assertIn("scanned=1", first_output.getvalue())
        self.assertIn("fixed=1", first_output.getvalue())
        self.assertIn("unresolved=0", first_output.getvalue())
        self.assertIn("scanned=0", second_output.getvalue())
        self.assertIn("fixed=0", second_output.getvalue())

    def test_repair_vehicle_liveries_leaves_existing_livery_alone(self):
        operator = Operator.objects.create(
            noc="OPL", name="Livery Operator", slug="livery-operator"
        )
        original = Livery.objects.create(
            name="Original", colour="#00ff00", external_id="orig"
        )
        replacement = Livery.objects.create(
            name="Replacement", colour="#ff0000", external_id="new"
        )
        vehicle = Vehicle.objects.create(operator=operator, code="301", livery=original)

        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/vehicles/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "veh-liv-2",
                            "operator": "OPL",
                            "code": "301",
                            "livery": "new",
                        }
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            side_effect=fake_get,
        ):
            call_command("repair_vehicle_liveries")

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.livery, original)
        self.assertNotEqual(vehicle.livery, replacement)
