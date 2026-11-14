import json
from datetime import datetime, timedelta, UTC
from unittest.mock import patch

import fakeredis
from django.test import TestCase
from django.utils import timezone

from busstops.models import DataSource, Operator, Service
from bustimes.models import Route, TimetableDataSource, Trip
from bustimes.management.commands.import_transxchange import get_open_data_operators
from vehicles.coverage import live_vehicle_payloads, operator_coverage, missing_timetables, coverage_alert
from vehicles.models import Vehicle, VehicleJourney
from vehicles.management.commands.import_bod_avl import Command


class CoverageAuditTest(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(name="BODS AVL")
        self.operator = Operator.objects.create(noc="TEST", name="Test operator")
        self.now = timezone.now()

    def vehicle(self, number=1, trip=None, source=None):
        vehicle = Vehicle.objects.create(operator=self.operator, code=str(number), slug=f"test-{number}")
        journey = VehicleJourney.objects.create(
            source=source or self.source, vehicle=vehicle, datetime=self.now,
            date=self.now.date(), trip=trip, service=trip.route.service if trip else None,
        )
        return vehicle, {"datetime": self.now.isoformat(), "journey_id": journey.pk}

    def test_ten_live_vehicles_without_timetables_are_flagged(self):
        live = dict((vehicle.pk, payload) for vehicle, payload in
                    (self.vehicle(n) for n in range(10)))
        rows = operator_coverage(live)
        self.assertEqual(rows[0]["tracking"], 10)
        self.assertEqual(rows[0]["services"], 0)
        self.assertEqual(rows[0]["trips"], 0)
        self.assertEqual(len(missing_timetables(rows)), 1)
        self.assertIn("TEST (10 live)", coverage_alert(rows))

    def test_small_operator_below_threshold_does_not_alert(self):
        vehicle, payload = self.vehicle()
        self.assertIsNone(coverage_alert(operator_coverage({vehicle.pk: payload})))

    def test_records_actual_trip_attachment_separately_from_timetable_coverage(self):
        service = Service.objects.create(source=self.source, line_name="1")
        service.operator.add(self.operator)
        route = Route.objects.create(source=self.source, service=service)
        trip = Trip.objects.create(route=route, start=timedelta(hours=12), end=timedelta(hours=13))
        vehicle, payload = self.vehicle(1, trip=trip)
        unmatched, other = self.vehicle(2)
        row = operator_coverage({vehicle.pk: payload, unmatched.pk: other})[0]
        self.assertEqual((row["tracking"], row["services"], row["trips"], row["live_with_trip"]),
                         (2, 1, 1, 1))

    def test_rail_embedded_schedules_are_not_reported_as_missing_bus_timetables(self):
        source = DataSource.objects.create(name="Signalbox")
        live = dict((vehicle.pk, payload) for vehicle, payload in
                    (self.vehicle(n, source=source) for n in range(10)))
        rows = operator_coverage(live)
        self.assertFalse(rows[0]["timetable_expected"])
        self.assertFalse(missing_timetables(rows))

    def test_expired_or_stale_cache_entries_are_not_tracking_vehicles(self):
        client = fakeredis.FakeStrictRedis()
        vehicle, payload = self.vehicle()
        client.set(f"vehicle{vehicle.pk}", json.dumps(payload))
        stale = dict(payload, datetime=(self.now - timedelta(minutes=20)).isoformat())
        client.set("vehicle9999", json.dumps(stale))
        client.set("vehicle10000", "broken json")
        client.set("vehicle123metadata", "{}")
        client.set("vehicle10001", json.dumps(dict(payload, datetime="not-a-date")))
        self.assertEqual(set(live_vehicle_payloads(client, now=self.now)), {vehicle.pk})


class MissingTripRetryTest(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(name="BODS AVL")
        self.operator = Operator.objects.create(noc="TEST")
        self.service = Service.objects.create(source=self.source, line_name="1")
        self.service.operator.add(self.operator)
        self.route = Route.objects.create(source=self.source, service=self.service)
        self.trip = Trip.objects.create(route=self.route, start=timedelta(hours=12),
                                        end=timedelta(hours=13), operator=self.operator)
        self.now = datetime(2026, 11, 13, 12, tzinfo=UTC)
        self.vehicle = Vehicle.objects.create(operator=self.operator, code="123", slug="test-123")
        self.journey = VehicleJourney.objects.create(
            source=self.source, vehicle=self.vehicle, service=self.service,
            datetime=self.now, date=self.now.date(), route_name="1",
        )
        self.vehicle.latest_journey = self.journey
        self.command = Command()
        self.command.source = self.source

    def test_existing_service_gets_another_chance_to_match_a_trip(self):
        item = {"RecordedAtTime": (self.now + timedelta(minutes=10)).isoformat(),
                "MonitoredVehicleJourney": {"OperatorRef": "TEST", "VehicleRef": "123",
                    "PublishedLineName": "1", "OriginAimedDepartureTime": self.now.isoformat()}}
        with patch.object(self.journey, "get_trip", return_value=self.trip) as match:
            result = self.command.get_journey(item, self.vehicle)
        match.assert_called_once()
        self.assertEqual(result.trip_id, self.trip.pk)

    def test_retries_are_limited_to_once_per_minute(self):
        with patch("vehicles.management.import_live_vehicles.monotonic", return_value=1000):
            self.assertTrue(self.command.should_retry_trip_match(self.vehicle))
        with patch("vehicles.management.import_live_vehicles.monotonic", return_value=1005):
            self.assertFalse(self.command.should_retry_trip_match(self.vehicle))
        with patch("vehicles.management.import_live_vehicles.monotonic", return_value=1060):
            self.assertTrue(self.command.should_retry_trip_match(self.vehicle))

    def test_already_matched_trip_is_not_retried(self):
        self.journey.trip = self.trip
        self.assertFalse(self.command.should_retry_trip_match(self.vehicle))

    def test_operator_without_any_timetable_waits_for_import(self):
        self.journey.service = None
        self.service.current = False
        self.service.save(update_fields=["current"])
        with patch("vehicles.management.import_live_vehicles.monotonic", return_value=1000):
            self.assertFalse(self.command.should_retry_trip_match(self.vehicle))
        service = Service.objects.create(source=self.source, line_name="2")
        service.operator.add(self.operator)
        route = Route.objects.create(source=self.source, service=service, code="replacement")
        Trip.objects.create(route=route, start=timedelta(hours=12), end=timedelta(hours=13))
        with patch("vehicles.management.import_live_vehicles.monotonic", return_value=1060):
            self.assertTrue(self.command.should_retry_trip_match(self.vehicle))


class TndsFallbackCoverageTest(TestCase):
    def test_configured_bods_source_without_imported_trips_does_not_block_fallback(self):
        operator = Operator.objects.create(noc="TEST")
        source = TimetableDataSource.objects.create(name="Configured BODS", active=True, complete=True)
        source.operators.add(operator)
        complete, _ = get_open_data_operators()
        self.assertNotIn(operator.pk, complete)

    def test_london_colour_is_created_without_legacy_primary_key(self):
        from bustimes.management.commands.import_transxchange import Command as ImportCommand
        colour = ImportCommand().london_bus_colour
        self.assertEqual(colour.background, "#dc241f")
        self.assertTrue(colour.pk)


class GroupTimetableRetryTest(MissingTripRetryTest):
    def test_group_timetables_allow_retry_without_direct_operator_services(self):
        from busstops.models import OperatorGroup
        group = OperatorGroup.objects.create(name="Test group", slug="test-group")
        sibling = Operator.objects.create(noc="SIBL", group=group)
        self.operator.group = group
        self.operator.save(update_fields=["group"])
        self.vehicle.operator = self.operator
        self.service.operator.set([sibling])
        self.journey.service = None
        with patch("vehicles.management.import_live_vehicles.monotonic", return_value=1000):
            self.assertTrue(self.command.should_retry_trip_match(self.vehicle))


class MidJourneyStopMatchTest(TestCase):
    def setUp(self):
        from busstops.models import StopPoint
        from bustimes.models import Calendar, StopTime
        self.now = datetime(2026, 11, 13, 12, 1, tzinfo=UTC)
        self.source = DataSource.objects.create(name="TfE")
        self.service = Service.objects.create(source=self.source, line_name="1")
        self.route = Route.objects.create(source=self.source, service=self.service, code="1")
        self.stop = StopPoint.objects.create(atco_code="620000123", naptan_code="Edin123", active=True)
        self.calendar = Calendar.objects.create(fri=True, start_date=self.now.date()-timedelta(days=7), end_date=self.now.date()+timedelta(days=7))
        self.trip = Trip.objects.create(route=self.route, calendar=self.calendar,
            start=timedelta(hours=11), end=timedelta(hours=13))
        StopTime.objects.create(trip=self.trip, stop=self.stop, sequence=10,
            departure=timedelta(hours=12))
        self.journey = VehicleJourney(service=self.service, datetime=self.now, date=self.now.date())

    def test_matches_midway_using_next_stop_time_instead_of_origin_time(self):
        matched = self.journey.get_trip(datetime=self.now, approximate_datetime=True, next_stop="EDIN123")
        self.assertEqual(matched.pk, self.trip.pk)

    def test_accepts_actual_atco_stop_identifier(self):
        matched = self.journey.get_trip(datetime=self.now, approximate_datetime=True, next_stop=self.stop.pk)
        self.assertEqual(matched.pk, self.trip.pk)

    def test_does_not_match_a_trip_from_another_operating_day(self):
        self.calendar.fri = False
        self.calendar.mon = True
        self.calendar.save()
        self.assertIsNone(self.journey.get_trip(datetime=self.now, approximate_datetime=True, next_stop="EDIN123"))


class ExcludedOperatorsTest(TestCase):
    def test_removed_operators_are_not_on_homepage_or_public_pages(self):
        for noc, slug in [("CAPCOT","cap-cotentin"),("ZDITM","zditm-szczecin"),("RTCSNV","rtcsnv")]:
            Operator.objects.create(noc=noc, name=slug, slug=slug)
        response = self.client.get("/")
        for slug in ["cap-cotentin","zditm-szczecin","rtcsnv"]:
            self.assertNotContains(response, f'/operators/{slug}')
            self.assertEqual(self.client.get(f"/operators/{slug}").status_code,404)

    def test_removed_providers_cannot_be_imported(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        for feed in ["rtcsnv","zditm","capcotentin"]:
            with self.assertRaises(CommandError):
                call_command("import_gtfs_feed",feed)
            with self.assertRaises(CommandError):
                call_command("import_gtfsr_feed",feed,immediate=True)


class TflScopedStopMatchTest(TestCase):
    def test_after_midnight_trip_uses_scoped_stop_refs_and_previous_calendar(self):
        from busstops.models import StopPoint
        from bustimes.models import Calendar, StopTime
        now = datetime(2026, 11, 14, 1, tzinfo=UTC)
        source = DataSource.objects.create(name="L")
        other = DataSource.objects.create(name="Other")
        service = Service.objects.create(source=source,line_name="N1")
        route = Route.objects.create(source=source,service=service)
        origin = StopPoint.objects.create(atco_code=f"{source.pk}:490000001", active=True)
        destination = StopPoint.objects.create(atco_code=f"{source.pk}:490000002", active=True)
        calendar = Calendar.objects.create(fri=True,start_date=now.date()-timedelta(days=7),end_date=now.date()-timedelta(days=1))
        trip = Trip.objects.create(route=route,calendar=calendar,start=timedelta(hours=25),end=timedelta(hours=26),destination=destination)
        StopTime.objects.create(trip=trip,stop=origin,sequence=1,departure=timedelta(hours=25))
        StopTime.objects.create(trip=trip,stop=destination,sequence=2,departure=timedelta(hours=26))
        journey = VehicleJourney(service=service,datetime=now)
        match = journey.get_trip(operator_ref="TFLO",origin_ref="490000001",destination_ref="490000002",departure_time=now)
        self.assertEqual(match,trip)
        self.assertEqual(journey.date,now.date()-timedelta(days=1))
        # An identically named stop in another source is not an alias here.
        other_origin = StopPoint.objects.create(atco_code=f"{other.pk}:490000001", active=True)
        StopTime.objects.filter(trip=trip,sequence=1).update(stop=other_origin)
        self.assertIsNone(journey.get_trip(operator_ref="TFLO",origin_ref="490000001",destination_ref="490000002",departure_time=now))
