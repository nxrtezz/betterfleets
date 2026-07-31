from django.test import SimpleTestCase, override_settings

from vehicles.train_gtfsr import (
    _include_route,
    route_matches_train_heuristic,
    stable_train_numeric_id,
)


class TrainGtfsrHelpersTest(SimpleTestCase):
    @override_settings(
        GTFSR_TRAIN_ROUTE_ALLOWLIST=frozenset(),
        GTFSR_TRAIN_ROUTE_SUBSTRINGS=("luas", "dart", "rail"),
    )
    def test_route_heuristic(self):
        self.assertTrue(route_matches_train_heuristic("LUASGreen"))
        self.assertTrue(route_matches_train_heuristic("4098_dart_1"))
        self.assertFalse(route_matches_train_heuristic("4099_68164"))

    def test_stable_id_deterministic(self):
        a = stable_train_numeric_id("vehicle-A")
        b = stable_train_numeric_id("vehicle-A")
        c = stable_train_numeric_id("vehicle-B")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    @override_settings(
        GTFSR_TRAIN_ROUTE_ALLOWLIST=frozenset(),
        GTFSR_TRAIN_ROUTE_FILTER_MODE="none",
        GTFSR_TRAIN_ROUTE_SUBSTRINGS=(),
    )
    def test_filter_mode_none_includes_any_route_id(self):
        self.assertTrue(_include_route("XC123"))
        self.assertTrue(_include_route(""))

    @override_settings(
        GTFSR_TRAIN_ROUTE_ALLOWLIST=frozenset({"only-this"}),
        GTFSR_TRAIN_ROUTE_FILTER_MODE="none",
    )
    def test_allowlist_overrides_filter_mode(self):
        self.assertTrue(_include_route("only-this"))
        self.assertFalse(_include_route("other"))
