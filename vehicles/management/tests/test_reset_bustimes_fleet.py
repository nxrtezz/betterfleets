from io import StringIO
from urllib.parse import urlparse
from unittest.mock import patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from busstops.models import DataSource, Operator
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
class ResetBustimesFleetCommandTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(name="Bustimes Fleet API")

    def _fake_sync_get(self, url, params=None, timeout=20):
        path = urlparse(url).path
        if path == "/api/operators/":
            return FakeResponse(
                200,
                [{"id": "OP1", "name": "Operator 1", "slug": "operator-1"}],
            )
        if path == "/api/vehicles/":
            return FakeResponse(
                200,
                [
                    {
                        "id": "veh-1",
                        "operator": "OP1",
                        "code": "100",
                        "registration": "AB12CDE",
                        "livery": "liv-1",
                    }
                ],
            )
        return FakeResponse(404, {})

    def _fake_repair_get(self, url, params=None, timeout=20):
        path = urlparse(url).path
        if path == "/api/vehicles/":
            return FakeResponse(
                200,
                [
                    {
                        "id": "veh-1",
                        "operator": "OP1",
                        "code": "100",
                        "registration": "AB12CDE",
                        "livery": "liv-1",
                    }
                ],
            )
        return FakeResponse(404, {})

    def test_resets_only_bustimes_imported_vehicles_and_reimports_them(self):
        operator = Operator.objects.create(noc="OP1", name="Operator 1", slug="operator-1")
        manual = Vehicle.objects.create(operator=operator, code="MAN1", is_manual=True)
        other_source = DataSource.objects.create(name="Other Source")
        untouched = Vehicle.objects.create(operator=operator, code="OTH1", source=other_source)
        imported = Vehicle.objects.create(
            operator=operator,
            code="OLD1",
            external_id="veh-old",
            source=self.source,
        )
        livery = Livery.objects.create(name="Demo Livery", colour="#ff0000", external_id="liv-1")

        with patch(
            "vehicles.management.commands.sync_bustimes_fleet.requests.Session.get",
            side_effect=self._fake_sync_get,
        ), patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            side_effect=self._fake_repair_get,
        ):
            call_command("reset_bustimes_fleet")

        self.assertFalse(Vehicle.objects.filter(pk=imported.pk).exists())
        self.assertTrue(Vehicle.objects.filter(pk=manual.pk).exists())
        self.assertTrue(Vehicle.objects.filter(pk=untouched.pk).exists())

        reimported = Vehicle.objects.get(external_id="veh-1")
        self.assertEqual(reimported.operator, operator)
        self.assertEqual(reimported.code, "100")
        self.assertEqual(reimported.livery, livery)
        self.assertEqual(reimported.source, self.source)

    def test_operator_filter_limits_reset_scope(self):
        operator_one = Operator.objects.create(noc="OP1", name="Operator 1", slug="operator-1")
        operator_two = Operator.objects.create(noc="OP2", name="Operator 2", slug="operator-2")
        keep_vehicle = Vehicle.objects.create(operator=operator_two, code="200", source=self.source)
        Vehicle.objects.create(operator=operator_one, code="100", source=self.source)
        Livery.objects.create(name="Demo Livery", colour="#ff0000", external_id="liv-1")

        with patch(
            "vehicles.management.commands.sync_bustimes_fleet.requests.Session.get",
            side_effect=self._fake_sync_get,
        ), patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            side_effect=self._fake_repair_get,
        ):
            call_command("reset_bustimes_fleet", operator="operator-1")

        self.assertTrue(Vehicle.objects.filter(pk=keep_vehicle.pk).exists())
        self.assertTrue(Vehicle.objects.filter(external_id="veh-1", operator=operator_one).exists())

    def test_dry_run_rolls_back_delete_and_reimport(self):
        operator = Operator.objects.create(noc="OP1", name="Operator 1", slug="operator-1")
        original = Vehicle.objects.create(operator=operator, code="100", source=self.source)
        Livery.objects.create(name="Demo Livery", colour="#ff0000", external_id="liv-1")
        output = StringIO()

        with patch(
            "vehicles.management.commands.sync_bustimes_fleet.requests.Session.get",
            side_effect=self._fake_sync_get,
        ), patch(
            "vehicles.management.commands.repair_vehicle_liveries.requests.Session.get",
            side_effect=self._fake_repair_get,
        ):
            call_command("reset_bustimes_fleet", dry_run=True, stdout=output)

        self.assertTrue(Vehicle.objects.filter(pk=original.pk).exists())
        self.assertIn("scanned=1 deleted=1", output.getvalue())
        self.assertIn("Dry run: all DB writes rolled back", output.getvalue())
