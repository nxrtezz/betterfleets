from django.test import SimpleTestCase

from vehicles.realtime import matcher


class BodsMatcherTests(SimpleTestCase):
    def test_get_vehicle_identity_includes_operator_and_vehicle(self):
        item = {
            "MonitoredVehicleJourney": {"OperatorRef": "OP1", "VehicleRef": "1234"},
            "Extensions": {"VehicleJourney": {"VehicleUniqueId": "U1"}},
        }
        self.assertEqual(matcher.get_vehicle_identity(item), "OP1:1234:U1")

    def test_get_journey_identity_uses_framed_ref_when_present(self):
        item = {
            "MonitoredVehicleJourney": {
                "LineRef": "7",
                "PublishedLineName": "7",
                "FramedVehicleJourneyRef": "J123",
                "OriginAimedDepartureTime": "2026-04-09T12:00:00+00:00",
                "DirectionRef": "outbound",
                "DestinationName": "Town Centre",
            }
        }
        self.assertEqual(
            matcher.get_journey_identity(item),
            "7 7 J123 2026-04-09T12:00:00+00:00 outbound Town Centre",
        )
