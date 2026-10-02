from datetime import date

from django.test import SimpleTestCase

from fleet.rail_replacement import discover_replacements, group_replacements


class FakeRTTClient:
    def __init__(self):
        self.details = {}

    def location_services(self, code, service_date):
        return [
            {
                "scheduleMetadata": {
                    "uniqueIdentity": f"gb-nr:{code}:{service_date}",
                    "identity": "0B00",
                    "modeType": "REPLACEMENT_BUS",
                    "operator": {"code": "SW", "name": "South Western Railway"},
                    "trainReportingIdentity": "0B00",
                }
            }
        ]

    def service(self, identity):
        return {
            "scheduleMetadata": {
                "uniqueIdentity": identity,
                "modeType": "REPLACEMENT_BUS",
                "operator": {"code": "SW", "name": "South Western Railway"},
            },
            "locations": [
                {
                    "location": {"shortCode": "SOU", "description": "Southampton Central"},
                    "temporalData": {
                        "departure": {"scheduleAdvertised": "2026-10-03T10:00:00"},
                    },
                },
                {
                    "location": {"shortCode": "BOU", "description": "Bournemouth"},
                    "temporalData": {
                        "arrival": {"scheduleAdvertised": "2026-10-03T10:45:00"},
                        "departure": {"scheduleAdvertised": "2026-10-03T10:47:00"},
                    },
                },
                {
                    "location": {"shortCode": "POO", "description": "Poole"},
                    "temporalData": {
                        "arrival": {"scheduleAdvertised": "2026-10-03T11:00:00"},
                    },
                },
            ],
        }


class RailReplacementTests(SimpleTestCase):
    def test_discovery_keeps_each_direction_and_slices_to_requested_endpoints(self):
        items = discover_replacements(
            [date(2026, 10, 3)],
            "SOU",
            "POO",
            operator_code="SW",
            client=FakeRTTClient(),
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(
            {item["locations"][0]["code"] for item in items},
            {"SOU", "POO"},
        )
        self.assertEqual(
            {tuple(location["code"] for location in item["locations"]) for item in items},
            {("SOU", "BOU", "POO"), ("POO", "BOU", "SOU")},
        )
        self.assertEqual(len(group_replacements(items)), 1)
