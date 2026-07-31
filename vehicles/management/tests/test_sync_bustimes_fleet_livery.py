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
class SyncBustimesFleetLiveryTests(TestCase):
    def test_imported_vehicle_gets_existing_livery(self):
        operator = Operator.objects.create(noc="OPL", name="Livery Operator", slug="livery-operator")
        livery = Livery.objects.create(name="Demo Livery", colour="#ff0000", external_id="liv-1")

        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/operators/":
                return FakeResponse(200, [{"id": "OPL", "name": "Livery Operator", "slug": "livery-operator"}])
            if path == "/api/vehicles/":
                return FakeResponse(
                    200,
                    [{
                        "id": "veh-liv-1",
                        "operator": "OPL",
                        "code": "300",
                        "livery": "liv-1",
                    }],
                )
            if path in {"/api/vehicletypes/", "/api/liveries/", "/api/garages/"}:
                return FakeResponse(404, {})
            return FakeResponse(404, {})

        with patch("vehicles.management.commands.sync_bustimes_fleet.requests.Session.get", side_effect=fake_get):
            call_command("sync_bustimes_fleet")

        vehicle = Vehicle.objects.get(operator=operator, code="300")
        self.assertEqual(vehicle.livery, livery)

    def test_livery_filter_refreshes_only_matching_vehicles(self):
        operator = Operator.objects.create(noc="OPL", name="Livery Operator", slug="livery-operator")
        livery = Livery.objects.create(
            name="Brighton & Hove", colour="#ff0000", external_id="36"
        )

        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/vehicles/":
                self.assertEqual(params["livery"], "36")
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "veh-36",
                            "operator": "OPL",
                            "code": "360",
                            "livery": "36",
                        },
                        {
                            "id": "veh-99",
                            "operator": "OPL",
                            "code": "990",
                            "livery": "99",
                        },
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.sync_bustimes_fleet.requests.Session.get",
            side_effect=fake_get,
        ):
            call_command("sync_bustimes_fleet", livery="36", skip_operators=True)

        vehicle = Vehicle.objects.get(operator=operator, code="360")
        self.assertEqual(vehicle.livery, livery)
        self.assertFalse(Vehicle.objects.filter(operator=operator, code="990").exists())
