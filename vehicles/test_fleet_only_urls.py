from django.test import TestCase

from busstops.models import Operator
from vehicles.models import Vehicle


class FleetOnlyURLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(
            noc="TST1", name="Test Operator", slug="test-operator"
        )
        cls.vehicle = Vehicle.objects.create(
            operator=cls.operator, code="100", fleet_number=100
        )

    def test_operator_page_redirects_to_fleet(self):
        response = self.client.get("/operators/test-operator")
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "/operators/test-operator/vehicles")

    def test_operator_map_url_renders(self):
        response = self.client.get("/operators/test-operator/map")
        self.assertEqual(response.status_code, 200)

    def test_tracking_urls_render_again(self):
        self.assertEqual(self.client.get("/map").status_code, 200)
        self.assertEqual(self.client.get("/maps").status_code, 301)
        self.assertEqual(self.client.get("/map/old").status_code, 200)
