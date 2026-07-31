from django.test import TestCase

from busstops.models import Operator
from vehicles.models import HistoricalFleet, Vehicle


class FleetOnlyURLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(
            noc="TST1", name="Test Operator", slug="test-operator"
        )
        cls.vehicle = Vehicle.objects.create(
            operator=cls.operator, code="100", fleet_number=100
        )
        cls.historical_fleet = HistoricalFleet.objects.create(
            operator=cls.operator, year=2018
        )
        cls.historical_vehicle = Vehicle.objects.create(
            operator=cls.operator,
            historical_fleet=cls.historical_fleet,
            code="H100",
            fleet_number=100,
        )

    def test_operator_page_redirects_to_fleet(self):
        response = self.client.get("/operators/test-operator")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/operators/test-operator/vehicles")

    def test_operator_map_url_renders(self):
        response = self.client.get("/operators/test-operator/map")
        self.assertEqual(response.status_code, 200)

    def test_operator_historical_fleet_urls(self):
        response = self.client.get("/operators/test-operator/vehicles/historical")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/operators/test-operator/vehicles/2018")
        self.assertEqual(response.status_code, 200)

    def test_historical_vehicle_urls_render(self):
        response = self.client.get("/operators/test-operator/vehicles/2018")
        self.assertContains(response, self.historical_vehicle.get_absolute_url())

        response = self.client.get(self.historical_vehicle.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_tracking_urls_render_again(self):
        self.assertEqual(self.client.get("/map").status_code, 200)
        self.assertEqual(self.client.get("/maps").status_code, 301)
        self.assertEqual(self.client.get("/map/old").status_code, 200)
