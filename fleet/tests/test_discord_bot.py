from django.test import SimpleTestCase

from fleet.discord_bot import create_vehicle_embed


class DiscordEmbedTests(SimpleTestCase):
    def test_vehicle_embed_contains_betterfleets_link_and_details(self):
        class VehicleStub:
            reg = "AB12 CDE"
            fleet_number = 123
            fleet_code = ""
            operator = "Example Buses"
            livery = "Blue"
            vehicle_type = "Single decker"

            def __str__(self):
                return "Example vehicle"

            def get_absolute_url(self):
                return "/vehicles/example"

        vehicle = VehicleStub()

        result = create_vehicle_embed(vehicle)

        self.assertEqual(result["url"], "https://betterfleets.org/vehicles/example")
        self.assertEqual(result["title"], "Example vehicle")
        self.assertEqual(
            {field["name"] for field in result["fields"]},
            {"Registration", "Fleet Number", "Operator", "Livery", "Type"},
        )
