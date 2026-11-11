"""RTT allocation parsing - pure functions, no DB needed."""

from django.test import SimpleTestCase

from vehicles.rtt import allocation_summary, tops_display_name


class AllocationSummaryTest(SimpleTestCase):
    def test_summary(self):
        service = {
            "allocationData": [
                {
                    "allocationIndex": 0,
                    "leadingClass": "700",
                    "passengerVehicles": 12,
                    "allocationItems": [
                        {
                            "stockType": "unit",
                            "identity": "700114",
                            "inReverse": False,
                            "identitySuppressed": False,
                            "numberOfVehicles": 12,
                        }
                    ],
                }
            ]
        }
        self.assertEqual(
            allocation_summary(service),
            {
                "tops": "700114",
                "leading_class": "700",
                "passenger_vehicles": 12,
            },
        )

    def test_no_allocations(self):
        self.assertIsNone(allocation_summary({}))
        self.assertIsNone(allocation_summary({"allocationData": []}))
        self.assertIsNone(
            allocation_summary({"allocationData": [{"allocationItems": []}]})
        )

    def test_picks_first_identity(self):
        service = {
            "allocationData": [
                {
                    "allocationItems": [
                        {"stockType": "unit", "identity": "387172"},
                        {"stockType": "unit", "identity": "387173"},
                    ]
                }
            ]
        }
        self.assertEqual(allocation_summary(service)["tops"], "387172")


class TopsDisplayNameTest(SimpleTestCase):
    def test_class_prefix_split(self):
        self.assertEqual(tops_display_name("700114", "700"), "700 114")
        self.assertEqual(tops_display_name("387172", "387"), "387 172")

    def test_no_class(self):
        self.assertEqual(tops_display_name("444045", None), "444045")
        self.assertEqual(tops_display_name("444045", "43"), "444045")
