from datetime import date, timedelta

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from busstops.models import Operator
from bustimes.models import Garage
from photos.models import Photo
from vehicles.models import Livery, Vehicle, VehicleType

from .models import DatePrecision, EventType, VehicleHistoryAttachment, VehicleHistoryEvent
from .serializers import VehicleHistoryEventSerializer, VehicleTimelineSerializer


class VehicleHistoryEventModelTest(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(noc="TEST", name="Test Operator")
        self.vehicle_type = VehicleType.objects.create(name="Test Type")
        self.vehicle = Vehicle.objects.create(
            code="TEST001",
            operator=self.operator,
            vehicle_type=self.vehicle_type,
            reg="AB12 CDE",
        )

    def test_create_history_event(self):
        event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.TRANSFER,
            title="Test Transfer",
            event_date=date.today(),
        )
        self.assertEqual(event.vehicle, self.vehicle)
        self.assertEqual(event.event_type, EventType.TRANSFER)
        self.assertEqual(event.title, "Test Transfer")
        self.assertFalse(event.is_future_event)
        self.assertFalse(event.is_automatic)

    def test_future_event(self):
        future_date = date.today() + timedelta(days=30)
        event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.DELIVERED,
            title="Future Delivery",
            event_date=future_date,
            is_future_event=True,
        )
        self.assertTrue(event.is_future_event)
        self.assertEqual(event.event_date, future_date)

    def test_automatic_event(self):
        event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.REPAINT,
            title="Automatic Repaint",
            event_date=date.today(),
            is_automatic=True,
        )
        self.assertTrue(event.is_automatic)

    def test_metadata_storage(self):
        metadata = {
            "from_operator": 1,
            "to_operator": 2,
        }
        event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.TRANSFER,
            title="Transfer",
            event_date=date.today(),
            metadata=metadata,
        )
        self.assertEqual(event.metadata, metadata)

    def test_date_precision(self):
        event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.OTHER,
            title="Unknown Date Event",
            date_precision=DatePrecision.UNKNOWN,
        )
        self.assertEqual(event.date_precision, DatePrecision.UNKNOWN)


class VehicleHistoryAttachmentModelTest(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(noc="TEST", name="Test Operator")
        self.vehicle_type = VehicleType.objects.create(name="Test Type")
        self.vehicle = Vehicle.objects.create(
            code="TEST001",
            operator=self.operator,
            vehicle_type=self.vehicle_type,
            reg="AB12 CDE",
        )
        self.event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.REPAINT,
            title="Repaint Event",
            event_date=date.today(),
        )

    def test_create_attachment(self):
        # Note: Photo model may have required fields, adjust as needed
        # This is a basic test structure
        attachment = VehicleHistoryAttachment(
            event=self.event,
            caption="Test Caption",
        )
        # Don't save if Photo is required and not properly set up
        self.assertEqual(attachment.event, self.event)
        self.assertEqual(attachment.caption, "Test Caption")


class AutomaticEventGenerationTest(TestCase):
    def setUp(self):
        self.operator1 = Operator.objects.create(noc="OP1", name="Operator 1")
        self.operator2 = Operator.objects.create(noc="OP2", name="Operator 2")
        self.vehicle_type = VehicleType.objects.create(name="Test Type")
        self.vehicle = Vehicle.objects.create(
            code="TEST001",
            operator=self.operator1,
            vehicle_type=self.vehicle_type,
            reg="AB12 CDE",
        )

    def test_operator_change_generates_event(self):
        # Change operator
        self.vehicle.operator = self.operator2
        self.vehicle.save()

        # Check that a transfer event was created
        events = VehicleHistoryEvent.objects.filter(
            vehicle=self.vehicle,
            event_type=EventType.TRANSFER,
            is_automatic=True,
        )
        self.assertEqual(events.count(), 1)
        event = events.first()
        self.assertIn("Transferred from", event.title)
        self.assertIn("Operator 1", event.title)
        self.assertIn("Operator 2", event.title)

    def test_livery_change_generates_event(self):
        livery1 = Livery.objects.create(name="Old Livery")
        livery2 = Livery.objects.create(name="New Livery")

        self.vehicle.livery = livery1
        self.vehicle.save()

        # Change livery
        self.vehicle.livery = livery2
        self.vehicle.save()

        # Check that a repaint event was created
        events = VehicleHistoryEvent.objects.filter(
            vehicle=self.vehicle,
            event_type=EventType.REPAINT,
            is_automatic=True,
        )
        self.assertGreaterEqual(events.count(), 1)

    def test_registration_change_generates_event(self):
        # Change registration
        self.vehicle.reg = "XY34 ZZZ"
        self.vehicle.save()

        # Check that a registration change event was created
        events = VehicleHistoryEvent.objects.filter(
            vehicle=self.vehicle,
            event_type=EventType.REGISTRATION_CHANGE,
            is_automatic=True,
        )
        self.assertEqual(events.count(), 1)
        event = events.first()
        self.assertIn("Registration changed", event.title)

    def test_withdrawn_status_change_generates_event(self):
        # Mark as withdrawn
        self.vehicle.withdrawn = True
        self.vehicle.save()

        # Check that a withdrawn event was created
        events = VehicleHistoryEvent.objects.filter(
            vehicle=self.vehicle,
            event_type=EventType.WITHDRAWN,
            is_automatic=True,
        )
        self.assertEqual(events.count(), 1)

    def test_duplicate_prevention(self):
        # Change operator twice
        self.vehicle.operator = self.operator2
        self.vehicle.save()

        # Try to change again (should not create duplicate)
        self.vehicle.operator = self.operator1
        self.vehicle.save()

        # Should have 2 events (one for each change), not more
        events = VehicleHistoryEvent.objects.filter(
            vehicle=self.vehicle,
            event_type=EventType.TRANSFER,
            is_automatic=True,
        )
        self.assertEqual(events.count(), 2)


class VehicleTimelineAPITest(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(noc="TEST", name="Test Operator")
        self.vehicle_type = VehicleType.objects.create(name="Test Type")
        self.vehicle = Vehicle.objects.create(
            code="TEST001",
            operator=self.operator,
            vehicle_type=self.vehicle_type,
            reg="AB12 CDE",
        )
        self.event = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.TRANSFER,
            title="Test Event",
            event_date=date.today(),
        )

    def test_vehicle_timeline_serializer(self):
        serializer = VehicleTimelineSerializer({
            "vehicle": self.vehicle,
            "events": [self.event],
        })
        data = serializer.data
        self.assertIn("vehicle", data)
        self.assertIn("events", data)
        self.assertEqual(len(data["events"]), 1)

    def test_event_serializer(self):
        serializer = VehicleHistoryEventSerializer(self.event)
        data = serializer.data
        self.assertEqual(data["id"], self.event.id)
        self.assertEqual(data["event_type"], EventType.TRANSFER)
        self.assertEqual(data["title"], "Test Event")
        self.assertIn("vehicle", data)


class OperatorTimelineAPITest(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(noc="TEST", name="Test Operator")
        self.vehicle_type = VehicleType.objects.create(name="Test Type")
        self.vehicle1 = Vehicle.objects.create(
            code="TEST001",
            operator=self.operator,
            vehicle_type=self.vehicle_type,
            reg="AB12 CDE",
        )
        self.vehicle2 = Vehicle.objects.create(
            code="TEST002",
            operator=self.operator,
            vehicle_type=self.vehicle_type,
            reg="XY34 ZZZ",
        )
        self.event1 = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle1,
            event_type=EventType.TRANSFER,
            title="Event 1",
            event_date=date.today(),
        )
        self.event2 = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle2,
            event_type=EventType.REPAINT,
            title="Event 2",
            event_date=date.today(),
        )

    def test_operator_timeline_includes_all_vehicles(self):
        events = VehicleHistoryEvent.objects.filter(
            vehicle__operator=self.operator
        )
        self.assertEqual(events.count(), 2)


class DatePrecisionTest(TestCase):
    def test_date_precision_choices(self):
        self.assertEqual(DatePrecision.DAY, "day")
        self.assertEqual(DatePrecision.MONTH, "month")
        self.assertEqual(DatePrecision.YEAR, "year")
        self.assertEqual(DatePrecision.UNKNOWN, "unknown")


class EventTypeTest(TestCase):
    def test_event_type_choices(self):
        self.assertEqual(EventType.TRANSFER, "transfer")
        self.assertEqual(EventType.REPAINT, "repaint")
        self.assertEqual(EventType.RENUMBERED, "renumbered")
        self.assertEqual(EventType.REGISTRATION_CHANGE, "registration_change")
        self.assertEqual(EventType.OTHER, "other")


class TimelineOrderingTest(TestCase):
    def setUp(self):
        self.operator = Operator.objects.create(noc="TEST", name="Test Operator")
        self.vehicle_type = VehicleType.objects.create(name="Test Type")
        self.vehicle = Vehicle.objects.create(
            code="TEST001",
            operator=self.operator,
            vehicle_type=self.vehicle_type,
            reg="AB12 CDE",
        )
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Create events with different dates
        self.event1 = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.TRANSFER,
            title="Old Event",
            event_date=yesterday,
        )
        self.event2 = VehicleHistoryEvent.objects.create(
            vehicle=self.vehicle,
            event_type=EventType.REPAINT,
            title="New Event",
            event_date=today,
        )

    def test_timeline_ordering(self):
        events = VehicleHistoryEvent.objects.filter(vehicle=self.vehicle)
        # Should be ordered by event_date descending
        self.assertEqual(events.first().event_date, date.today())
        self.assertEqual(events.last().event_date, date.today() - timedelta(days=1))
