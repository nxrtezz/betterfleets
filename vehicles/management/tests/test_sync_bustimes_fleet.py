from urllib.parse import urlparse
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from busstops.models import Operator
from vehicles.models import Vehicle


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
class SyncBustimesFleetCommandTests(TestCase):
    def run_sync(self, operators_payload, vehicles_payload):
        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/operators/":
                return FakeResponse(200, operators_payload)
            if path == "/api/vehicles/":
                return FakeResponse(200, vehicles_payload)
            if path in {"/api/vehicletypes/", "/api/liveries/", "/api/garages/"}:
                return FakeResponse(404, {})
            return FakeResponse(404, {})

        with patch("vehicles.management.commands.sync_bustimes_fleet.requests.Session.get", side_effect=fake_get):
            call_command("sync_bustimes_fleet")

    def test_creates_operator_and_vehicle_from_api(self):
        self.run_sync(
            operators_payload=[{"id": "OP1", "name": "Operator 1", "slug": "operator-1", "mode": "bus"}],
            vehicles_payload=[
                {
                    "id": "veh-1",
                    "operator": "OP1",
                    "code": "100",
                    "registration": "AB12CDE",
                    "fleet_num": 100,
                }
            ],
        )

        operator = Operator.objects.get(pk="OP1")
        self.assertEqual(operator.name, "Operator 1")

        vehicle = Vehicle.objects.get(operator=operator, code="100")
        self.assertEqual(vehicle.reg, "AB12CDE")
        self.assertEqual(vehicle.external_id, "veh-1")

    def test_manual_vehicle_fields_are_not_overwritten(self):
        operator = Operator.objects.create(noc="OP2", name="Manual Operator", slug="manual-operator")
        vehicle = Vehicle.objects.create(
            operator=operator,
            code="MAN1",
            reg="ZZ11ZZZ",
            external_id="veh-man",
            is_manual=True,
        )

        self.run_sync(
            operators_payload=[{"id": "OP2", "name": "Manual Operator", "slug": "manual-operator"}],
            vehicles_payload=[
                {
                    "id": "veh-man",
                    "operator": "OP2",
                    "code": "API1",
                    "registration": "AA11AAA",
                }
            ],
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.code, "MAN1")
        self.assertEqual(vehicle.reg, "ZZ11ZZZ")

    def test_fallback_matching_updates_existing_vehicle_without_external_id(self):
        operator = Operator.objects.create(noc="OP3", name="Fallback Operator", slug="fallback-operator")
        vehicle = Vehicle.objects.create(
            operator=operator,
            code="200",
            reg="AA00AAA",
            name="Old Name",
        )

        self.run_sync(
            operators_payload=[{"id": "OP3", "name": "Fallback Operator", "slug": "fallback-operator"}],
            vehicles_payload=[
                {
                    "id": "veh-200",
                    "operator": "OP3",
                    "code": "200",
                    "name": "New Name",
                }
            ],
        )

        vehicle.refresh_from_db()
        self.assertEqual(vehicle.external_id, "veh-200")
        self.assertEqual(vehicle.name, "New Name")