from urllib.parse import urlparse
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from busstops.models import Operator
from vehicles.models import Livery, Vehicle


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
class AuditBustimesVehicleLiveriesTests(TestCase):
    def test_mismatch_reassigns_to_bustimes_livery(self):
        operator = Operator.objects.create(noc="OPL", name="Test Operator", slug="test-operator")
        wrong = Livery.objects.create(name="Wrong Name", colour="#ff0000", left_css="a", right_css="b")
        vehicle = Vehicle.objects.create(operator=operator, code="300", livery=wrong)

        def fake_get(url, params=None, timeout=30):
            path = urlparse(url).path
            if path == "/api/vehicles/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "veh-1",
                            "operator": {"id": "OPL", "slug": "test-operator", "name": "Test Operator"},
                            "code": "300",
                            "livery": {
                                "id": "1078",
                                "name": "Correct Livery",
                                "left": "linear-gradient(#e41,#f90)",
                                "right": "linear-gradient(#f90,#e41)",
                            },
                        }
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.audit_bustimes_vehicle_liveries.requests.Session.get",
            side_effect=fake_get,
        ):
            call_command("audit_bustimes_vehicle_liveries", verbosity=0)

        vehicle.refresh_from_db()
        self.assertNotEqual(vehicle.livery_id, wrong.pk)
        self.assertEqual(vehicle.livery.external_id, "1078")
        self.assertEqual(vehicle.livery.name, "Correct Livery")
        self.assertEqual(vehicle.livery.left_css, "linear-gradient(#e41,#f90)")

    def test_manual_vehicle_is_skipped(self):
        operator = Operator.objects.create(noc="OPL", name="Test Operator", slug="test-operator")
        wrong = Livery.objects.create(name="Wrong Name", colour="#ff0000", left_css="a", right_css="b")
        vehicle = Vehicle.objects.create(operator=operator, code="300", livery=wrong, is_manual=True)

        def fake_get(url, params=None, timeout=30):
            path = urlparse(url).path
            if path == "/api/vehicles/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "veh-1",
                            "operator": {"id": "OPL"},
                            "code": "300",
                            "livery": {
                                "id": "1078",
                                "name": "Correct Livery",
                                "left": "linear-gradient(#e41,#f90)",
                                "right": "linear-gradient(#f90,#e41)",
                            },
                        }
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.audit_bustimes_vehicle_liveries.requests.Session.get",
            side_effect=fake_get,
        ):
            call_command("audit_bustimes_vehicle_liveries", verbosity=0)

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.livery_id, wrong.pk)

