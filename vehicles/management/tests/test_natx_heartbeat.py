"""National Express stationary reports must refresh live tracking."""
import json
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

import fakeredis
import time_machine
from django.test import TestCase, override_settings

from busstops.models import DataSource, Operator
from vehicles.models import Vehicle, VehicleJourney
from vehicles.management.commands.import_bod_avl import Command


@override_settings(CHANNEL_LAYERS={})
class NationalExpressHeartbeatTest(TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 13, 12, tzinfo=UTC)
        self.source = DataSource.objects.create(name="BODS AVL")
        self.operator = Operator.objects.create(noc="NATX")
        self.vehicle = Vehicle.objects.create(operator=self.operator, code="TEST123", slug="natx-test123")
        self.journey = VehicleJourney.objects.create(
            source=self.source, vehicle=self.vehicle, date=self.now.date(),
            datetime=self.now, route_name="123",
        )
        self.vehicle.latest_journey = self.journey
        self.vehicle.save(update_fields=["latest_journey"])
        self.command = Command()
        self.command.source = self.source
        self.command.eager_progress = False
        self.redis = fakeredis.FakeStrictRedis()
        self.patchers = [
            patch("vehicles.management.import_live_vehicles.redis_client", self.redis),
            patch("vehicles.utils.redis_client", self.redis),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def report(self, when, operator="NATX", longitude="-0.149"):
        return {
            "RecordedAtTime": when.isoformat(),
            "MonitoredVehicleJourney": {
                "OperatorRef": operator, "VehicleRef": "TEST123",
                "VehicleLocation": {"Longitude": longitude, "Latitude": "51.493"},
            },
        }

    def ingest(self, item, now):
        self.command.source.datetime = now
        self.command.handle_item(item, now=now, vehicle=self.vehicle, keep_journey=True)
        self.command.save()

    def cached(self):
        raw = self.redis.get(f"vehicle{self.vehicle.pk}")
        return json.loads(raw) if raw else None

    def test_fresh_stationary_reports_remain_live_beyond_fifteen_minutes(self):
        with time_machine.travel(self.now, tick=False) as clock:
            for minute in (0, 4, 8, 12, 16, 20, 24):
                now = self.now + timedelta(minutes=minute)
                clock.move_to(now)
                self.ingest(self.report(now), now)
                self.assertIsNotNone(self.cached())
                self.assertEqual(self.cached()["datetime"], now.isoformat())
                self.assertGreater(self.redis.ttl(f"vehicle{self.vehicle.pk}"), 850)
            self.assertEqual(self.cached()["coordinates"], [-0.149, 51.493])
            self.assertEqual(self.cached()["journey_id"], self.journey.pk)

    def test_duplicate_timestamp_does_not_refresh_expiry(self):
        with time_machine.travel(self.now, tick=False) as clock:
            item = self.report(self.now)
            self.ingest(item, self.now)
            clock.move_to(self.now + timedelta(minutes=4))
            self.ingest(item, self.now + timedelta(minutes=4))
            self.assertLessEqual(self.redis.ttl(f"vehicle{self.vehicle.pk}"), 660)
            self.assertEqual(self.cached()["datetime"], self.now.isoformat())

    def test_out_of_order_report_does_not_overwrite_position(self):
        with time_machine.travel(self.now, tick=False):
            self.ingest(self.report(self.now), self.now)
            self.ingest(self.report(self.now - timedelta(minutes=1), longitude="-0.2"), self.now)
            self.assertEqual(self.cached()["coordinates"], [-0.149, 51.493])
            self.assertEqual(self.cached()["datetime"], self.now.isoformat())

    def test_fifteen_minute_stale_report_is_not_shown_live(self):
        with time_machine.travel(self.now, tick=False):
            self.ingest(self.report(self.now - timedelta(minutes=16)), self.now)
            self.assertIsNone(self.cached())

    def test_other_operator_stale_coordinate_protection_remains(self):
        with time_machine.travel(self.now, tick=False) as clock:
            self.ingest(self.report(self.now, operator="SCOX"), self.now)
            now = self.now + timedelta(minutes=4)
            clock.move_to(now)
            self.ingest(self.report(now, operator="SCOX"), now)
            self.assertEqual(self.cached()["datetime"], self.now.isoformat())
            self.assertLessEqual(self.redis.ttl(f"vehicle{self.vehicle.pk}"), 660)

    def test_stopped_feed_still_expires(self):
        with time_machine.travel(self.now, tick=False) as clock:
            self.ingest(self.report(self.now), self.now)
            clock.move_to(self.now + timedelta(minutes=16))
            self.assertIsNone(self.cached())
