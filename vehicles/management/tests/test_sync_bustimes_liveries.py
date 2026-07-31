from unittest.mock import patch
from urllib.parse import urlparse

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings

from vehicles.models import Livery


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
class SyncBustimesLiveriesCommandTests(TestCase):
    def test_sync_succeeds_when_lightningcss_is_unavailable(self):
        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/liveries/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": "liv-1",
                            "name": "Demo Livery",
                            "left": "linear-gradient(#ff0000,#ffffff)",
                            "right": "linear-gradient(#ffffff,#ff0000)",
                            "colour": "#ff0000",
                        }
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.sync_bustimes_liveries.requests.Session.get",
            side_effect=fake_get,
        ):
            with patch("vehicles.models.subprocess.run", side_effect=FileNotFoundError):
                call_command("sync_bustimes_liveries")

        livery = Livery.objects.get(external_id="liv-1")
        self.assertEqual(livery.name, "Demo Livery")
        self.assertEqual(livery.left_css, "linear-gradient(#ff0000,#ffffff)")
        self.assertEqual(livery.right_css, "linear-gradient(#ffffff,#ff0000)")

    def test_sync_can_target_single_livery_and_refresh_matching_vehicles(self):
        def fake_get(url, params=None, timeout=20):
            path = urlparse(url).path
            if path == "/api/liveries/":
                return FakeResponse(
                    200,
                    [
                        {
                            "id": 35,
                            "name": "Other Livery",
                            "left_css": "linear-gradient(#000000,#ffffff)",
                            "right_css": "linear-gradient(#ffffff,#000000)",
                        },
                        {
                            "id": 36,
                            "name": "Brighton & Hove",
                            "left_css": "linear-gradient(#ff0000,#ffffcb)",
                            "right_css": "linear-gradient(#ffffcb,#ff0000)",
                        },
                    ],
                )
            return FakeResponse(404, {})

        with patch(
            "vehicles.management.commands.sync_bustimes_liveries.requests.Session.get",
            side_effect=fake_get,
        ):
            with patch("vehicles.management.commands.sync_bustimes_liveries.call_command") as mocked_call_command:
                call_command("sync_bustimes_liveries", livery="36")

        self.assertTrue(Livery.objects.filter(external_id="36", name="Brighton & Hove").exists())
        self.assertFalse(Livery.objects.filter(external_id="35").exists())
        mocked_call_command.assert_called_once()
        self.assertEqual(mocked_call_command.call_args.args[0], "sync_bustimes_fleet")
        self.assertEqual(mocked_call_command.call_args.kwargs["livery"], "36")
        self.assertTrue(mocked_call_command.call_args.kwargs["skip_operators"])
