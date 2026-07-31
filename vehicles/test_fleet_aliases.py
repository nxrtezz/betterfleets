from django.test import TestCase

from vehicles.models import Vehicle, VehicleType


class FleetAliasModelTests(TestCase):
    def test_vehicle_alias_fields_map_to_existing_columns(self):
        vehicle = Vehicle(code="100")
        vehicle.registration = "ab12 cde"
        vehicle.fleet_num = 321

        self.assertEqual(vehicle.reg, "ab12 cde")
        self.assertEqual(vehicle.fleet_number, 321)

    def test_vehicle_type_type_alias_maps_to_style(self):
        vehicle_type = VehicleType(name="Test Type")
        vehicle_type.type = "single decker"

        self.assertEqual(vehicle_type.style, "single decker")
        self.assertEqual(vehicle_type.type, "single decker")