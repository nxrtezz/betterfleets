from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import zipfile

from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone

from busstops.models import DataSource, Operator, OperatorGroup, Region, Service
from bustimes.models import Route, TimetableDataSource
from bustimes.management.commands.import_bod_timetables import clean_up, handle_file
from vehicles.models import Vehicle, VehicleJourney
from vehicles.management.commands.import_bod_avl import Command as BodCommand
from vehicles.management.commands.import_signalbox import Command as RailCommand


class SourceIsolationTest(TestCase):
    def test_cleanup_keeps_another_provider_for_same_operator(self):
        operator = Operator.objects.create(noc="TEST")
        a = TimetableDataSource.objects.create(name="A")
        b = TimetableDataSource.objects.create(name="B")
        a.operators.add(operator)
        b.operators.add(operator)
        current = DataSource.objects.create(name="current", source=a)
        old = DataSource.objects.create(name="old", source=a)
        other = DataSource.objects.create(name="other", source=b)
        def route(source, code):
            service = Service.objects.create(line_name=code, source=source, current=True)
            service.operator.add(operator)
            return Route.objects.create(source=source, code=code, service=service)
        new_route = route(current, "1")
        old_route = route(old, "2")
        protected = route(other, "3")
        clean_up(a, [current])
        old_route.refresh_from_db()
        protected.refresh_from_db()
        self.assertIsNone(old_route.service_id)
        self.assertIsNotNone(protected.service_id)
        self.assertTrue(Service.objects.get(pk=protected.service_id).current)

    def test_downloaded_relative_path_is_not_prefixed_twice(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            relative = Path(directory).relative_to(Path.cwd())
            file = relative / "dataset.zip"
            with zipfile.ZipFile(file, "w") as archive:
                archive.writestr("service.xml", "<TransXChange/>")
            command = Mock()
            with override_settings(DATA_DIR=relative):
                handle_file(command, file)
            command.handle_file.assert_called_once()
            command.finish_task.assert_called_once()


class FleetIdentityTest(TestCase):
    def setUp(self):
        self.group = OperatorGroup.objects.create(name="Group", slug="test-group")
        self.operator = Operator.objects.create(noc="TEST", group=self.group)
        self.sibling = Operator.objects.create(noc="SIBL", group=self.group)
        self.other = Operator.objects.create(noc="OTHR")
        self.source = DataSource.objects.create(name="BODS")
        self.command = BodCommand()
        self.command.source = self.source
        self.command.get_operator = lambda code: [self.operator]

    def item(self, ref="123"):
        return {"MonitoredVehicleJourney": {"OperatorRef": "TEST", "VehicleRef": ref}}

    def test_reuses_group_vehicle_by_fleet_code(self):
        existing = Vehicle.objects.create(operator=self.sibling, code="legacy",
                                          fleet_code="123", slug="legacy")
        found, created = self.command.get_vehicle(self.item())
        self.assertFalse(created)
        self.assertEqual(found.pk, existing.pk)
        self.assertEqual(Vehicle.objects.count(), 1)

    def test_does_not_reuse_other_group_fleet_number(self):
        other = Vehicle.objects.create(operator=self.other, code="other",
                                       fleet_code="123", slug="other")
        found, created = self.command.get_vehicle(self.item())
        self.assertTrue(created)
        self.assertNotEqual(found.pk, other.pk)

    def test_alphanumeric_fleet_code(self):
        existing = Vehicle.objects.create(operator=self.operator, code="legacy",
                                          fleet_code="AB12", slug="legacy")
        found, created = self.command.get_vehicle(self.item("AB12"))
        self.assertEqual(found.pk, existing.pk)
        self.assertFalse(created)


class RailHandoverTest(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(name="Signalbox")
        self.operator = Operator.objects.create(noc="SW")
        self.vehicle = Vehicle.objects.create(operator=self.operator, code="444001", slug="444001")
        self.now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.date = self.now.date()
        self.command = RailCommand()
        self.command.source = self.source
        self.previous = VehicleJourney.objects.create(
            source=self.source, operator=self.operator, vehicle=self.vehicle,
            date=self.date, datetime=self.now - timedelta(hours=1),
            data={"destination_crs": "AAA", "stops": [
                {"arrival": (self.now - timedelta(minutes=10)).isoformat()}],
                "rtt": {"tops": "444001", "units": [{"tops": "444001", "cars": 5}]}}
        )
        self.next = VehicleJourney.objects.create(
            source=self.source, operator=self.operator,
            date=self.date, datetime=self.now,
            data={"origin_crs": "AAA", "uid": "A12345", "toc": "SW"}
        )

    @patch("vehicles.management.commands.import_signalbox.redis_client", None)
    def test_carries_single_unit_and_marks_inference(self):
        self.command._carry_allocation(self.next)
        self.next.refresh_from_db()
        self.assertEqual(self.next.vehicle_id, self.vehicle.pk)
        self.assertEqual(self.next.data["allocation_inferred"]["from_journey"], self.previous.pk)

    @patch("vehicles.management.commands.import_signalbox.redis_client", None)
    def test_rejects_ambiguous_turnaround(self):
        other = Vehicle.objects.create(operator=self.operator, code="444002", slug="444002")
        VehicleJourney.objects.create(
            source=self.source, operator=self.operator, vehicle=other,
            date=self.date, datetime=self.now - timedelta(hours=1),
            data=self.previous.data)
        self.command._carry_allocation(self.next)
        self.assertIsNone(self.next.vehicle_id)

    @patch("vehicles.management.commands.import_signalbox.redis_client", None)
    def test_rejects_coupled_formation(self):
        self.previous.data["rtt"]["units"].append({"tops": "444002"})
        self.previous.save(update_fields=["data"])
        self.command._carry_allocation(self.next)
        self.assertIsNone(self.next.vehicle_id)

    @patch("vehicles.management.commands.import_signalbox.redis_client", None)
    def test_rejects_long_gap(self):
        self.next.datetime += timedelta(hours=2)
        self.command._carry_allocation(self.next)
        self.assertIsNone(self.next.vehicle_id)

    def test_inferred_allocations_still_queued_for_confirmation(self):
        self.command.rtt = Mock(configured=True)
        self.next.vehicle = self.vehicle
        self.next.data["allocation_inferred"] = {"from_journey": self.previous.pk}
        self.command._queue_rtt(self.next)
        self.assertEqual(len(self.command.rtt_heap), 1)


class RailQueueTest(SimpleTestCase):
    def journey(self, uid, toc, now):
        return SimpleNamespace(data={"uid": uid, "toc": toc}, vehicle_id=None,
                               date=now.date(), datetime=now)

    @patch("vehicles.management.commands.import_signalbox.time.time", return_value=10000)
    def test_fifo_and_backlog_preference(self, clock):
        now = timezone.now()
        command = RailCommand()
        command.rtt = Mock(configured=True)
        first = self.journey("FIRST", "GW", now)
        second = self.journey("SECOND", "SW", now)
        command._queue_rtt(first)
        command._queue_rtt(second)
        command._rtt_done = Mock(return_value=False)
        command._apply_rtt = Mock()
        command._process_rtt()
        command.rtt.service.assert_called_with("FIRST", now.date().isoformat())
        command._rtt_next = 0
        for i in range(200):
            command._queue_rtt(self.journey(f"OTHER{i}", "GW", now))
        command._process_rtt()
        command.rtt.service.assert_called_with("SECOND", now.date().isoformat())


class FleetMergeHistoryTest(FleetIdentityTest):
    def test_merges_duplicate_history_into_existing_vehicle(self):
        from vehicles.utils import reuse_tracking_vehicle
        existing = Vehicle.objects.create(operator=self.sibling, code="legacy",
                                          fleet_code="123", slug="legacy")
        duplicate = Vehicle.objects.create(operator=self.operator, code="123",
                                           fleet_code="123", slug="new")
        journey = VehicleJourney.objects.create(vehicle=duplicate, source=self.source,
                                                date=timezone.localdate(), datetime=timezone.now())
        found = reuse_tracking_vehicle(duplicate)
        journey.refresh_from_db()
        self.assertEqual(found.pk, existing.pk)
        self.assertEqual(journey.vehicle_id, existing.pk)
        self.assertFalse(Vehicle.objects.filter(pk=duplicate.pk).exists())


class FerryMatchTest(TestCase):
    def setUp(self):
        from datetime import datetime, timezone as dt_timezone, date
        from busstops.models import StopPoint
        from bustimes.models import Calendar, Trip
        self.source = DataSource.objects.create(name="Red Funnel")
        self.service = Service.objects.create(line_name="RedFunnel", source=self.source)
        self.stop = StopPoint.objects.create(atco_code="RF-EAS", active=True)
        self.route = Route.objects.create(source=self.source, service=self.service)
        self.calendar = Calendar.objects.create(fri=True, start_date=date(2026, 11, 1),
                                                 end_date=date(2026, 11, 30))
        self.trip = Trip.objects.create(route=self.route, calendar=self.calendar,
                                       destination=self.stop, start=timedelta(hours=19, minutes=30),
                                       end=timedelta(hours=20, minutes=30))
        self.journey = VehicleJourney(datetime=datetime(2026, 11, 13, 20, 19, tzinfo=dt_timezone.utc),
                                      date=date(2026, 11, 13), service=self.service,
                                      route_name="RedFunnel", destination="Isle of Wight")

    def test_restart_mid_crossing_matches_underway_sailing(self):
        from vehicles.management.commands.import_redfunnel import Command
        self.assertEqual(Command().match_trip(self.journey).pk, self.trip.pk)

    def test_ambiguous_underway_sailing_is_not_guessed(self):
        from bustimes.models import Trip
        from vehicles.management.commands.import_redfunnel import Command
        Trip.objects.create(route=self.route, calendar=self.calendar, destination=self.stop,
                            start=timedelta(hours=19, minutes=35), end=timedelta(hours=20, minutes=35))
        self.assertIsNone(Command().match_trip(self.journey))

    def test_expired_crossing_is_not_matched(self):
        from vehicles.management.commands.import_redfunnel import Command
        self.journey.datetime += timedelta(hours=2)
        self.assertIsNone(Command().match_trip(self.journey))


class StagecoachDuplicateTest(FleetIdentityTest):
    def test_existing_group_duplicates_do_not_crash_feed(self):
        from vehicles.management.commands.import_stagecoach_avl import Command
        a = Vehicle.objects.create(operator=self.operator, code="123", fleet_code="123", slug="first")
        b = Vehicle.objects.create(operator=self.sibling, code="123", fleet_code="123", slug="second")
        command = Command()
        command.source = self.source
        command.operators = {self.operator.pk: self.operator, self.sibling.pk: self.sibling}
        found, created = command.get_vehicle({"fn": "123", "oc": self.operator.pk, "hg": "1"})
        self.assertEqual(found.pk, a.pk)
        self.assertFalse(created)
        self.assertFalse(Vehicle.objects.filter(pk=b.pk).exists())


class InvalidDisruptionPeriodTest(TestCase):
    def test_reversed_upstream_period_is_skipped(self):
        from google.transit import gtfs_realtime_pb2
        from disruptions.gtfsr_alerts import handle_alert
        from disruptions.models import Situation
        source = DataSource.objects.create(name="test-alerts")
        alert = gtfs_realtime_pb2.Alert()
        text = alert.header_text.translation.add()
        text.language = "en"
        text.text = "Test disruption"
        period = alert.active_period.add()
        period.start = 200
        period.end = 100
        feed = SimpleNamespace(skip_alert_headers=set(), stop_id_prefix="")
        with self.assertLogs("disruptions.gtfsr_alerts", level="WARNING"):
            self.assertIsNone(handle_alert("test", alert, feed, source, None, {}))
        self.assertFalse(Situation.objects.exists())
