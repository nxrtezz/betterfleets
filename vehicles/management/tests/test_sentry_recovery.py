from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import requests
from django.db import connection
from django.test import SimpleTestCase, TestCase
from tenacity import wait_none

from busstops.models import DataSource, Operator, Service
from bustimes.models import Route, Trip
from vehicles.models import Vehicle, VehicleJourney
from vehicles.management.commands.import_bod_avl import Command as BodCommand
from vehicles.management.commands.import_live_jersey import Command as JerseyCommand
from vehicles.management.import_live_vehicles import ImportLiveVehiclesCommand


class FeedRetryTest(SimpleTestCase):
    def setUp(self):
        self.command = JerseyCommand()
        self.command.session = Mock()
        self.response = Mock()
        self.response.json.return_value = {"updates": []}
        self.fetch = ImportLiveVehiclesCommand.get_items.retry_with(wait=wait_none())

    def test_timeout_recovers_without_error_event(self):
        self.command.session.get.side_effect = [requests.ReadTimeout(), self.response]
        with self.assertLogs("vehicles.management.import_live_vehicles", level="WARNING") as logs:
            self.assertEqual(self.fetch(self.command), {"updates": []})
        self.assertEqual(self.command.session.get.call_count, 2)
        self.assertEqual([record.levelname for record in logs.records], ["WARNING"])

    def test_persistent_timeout_stops_after_three_attempts(self):
        self.command.session.get.side_effect = requests.ReadTimeout()
        with self.assertLogs("vehicles.management.import_live_vehicles", level="WARNING"):
            with self.assertRaises(requests.ReadTimeout):
                self.fetch(self.command)
        self.assertEqual(self.command.session.get.call_count, 3)

    def test_programming_error_is_not_retried(self):
        self.command.session.get.side_effect = ValueError("invalid response")
        with self.assertRaises(ValueError):
            self.fetch(self.command)
        self.command.session.get.assert_called_once()

    def test_exhaustion_is_reported_and_next_poll_remains_scheduled(self):
        self.command.source = Mock(name="source")
        with patch.object(self.command, "get_changed_items", side_effect=requests.ReadTimeout()):
            with self.assertLogs("vehicles.management.import_live_vehicles", level="ERROR"):
                self.assertEqual(self.command.update(), self.command.wait)

    def test_jersey_uses_https(self):
        self.assertTrue(self.command.url.startswith("https://"))


class OperatorTransferCollisionTest(TestCase):
    def test_trip_operator_collision_preserves_tracking_and_database_transaction(self):
        original = Operator.objects.create(noc="PLYC")
        target = Operator.objects.create(noc="TFCN")
        source = DataSource.objects.create(name="BODS collision regression")
        service = Service.objects.create(line_name="1", source=source)
        service.operator.add(target)
        route = Route.objects.create(service=service, source=source)
        trip = Trip.objects.create(route=route, operator=target, start=timedelta(hours=12), end=timedelta(hours=13))
        vehicle = Vehicle.objects.create(operator=original, code="COLLISION", slug="collision-original")
        duplicate = Vehicle.objects.create(operator=target, code="collision", slug="collision-target")
        command = BodCommand()
        command.source = source
        command.get_operator = Mock(return_value=[original])
        command.get_service = Mock(return_value=service)
        item = {
            "RecordedAtTime": datetime(2026, 11, 14, 12, 1, tzinfo=UTC).isoformat(),
            "Extensions": None,
            "MonitoredVehicleJourney": {
                "OperatorRef": "PLYC", "VehicleRef": "COLLISION",
                "PublishedLineName": "1", "VehicleJourneyRef": "trip-1",
                "OriginAimedDepartureTime": datetime(2026, 11, 14, 12, tzinfo=UTC).isoformat(),
            },
        }
        with patch.object(VehicleJourney, "get_trip", return_value=trip):
            journey = command.get_journey(item, vehicle)
        self.assertEqual(journey.trip, trip)
        self.assertEqual(vehicle.operator_id, original.pk)
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.operator_id, original.pk)
        self.assertTrue(Vehicle.objects.filter(pk=duplicate.pk).exists())
        self.assertFalse(connection.needs_rollback)
        journey.date = journey.datetime.date()
        journey.save()
        self.assertTrue(VehicleJourney.objects.filter(pk=journey.pk).exists())
