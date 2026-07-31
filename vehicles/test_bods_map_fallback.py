from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from busstops.models import DataSource, Operator, OperatorCode


@override_settings(BODS_API_KEY="test-bods-key")
class BodsMapFallbackTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(
            noc="TST1",
            name="Test Operator",
            slug="test-operator",
        )
        cls.source = DataSource.objects.create(
            name="Bus Open Data",
            url="https://data.bus-data.dft.gov.uk/api/v1/datafeed/",
        )
        OperatorCode.objects.create(
            operator=cls.operator,
            source=cls.source,
            code="BODSREF",
        )

    def test_operator_map_falls_back_to_bods_feed(self):
        response = Mock()
        response.headers = {"content-type": "text/xml"}
        response.content = b"""
<Siri xmlns="http://www.siri.org.uk/siri" version="2.0">
  <ServiceDelivery>
    <VehicleMonitoringDelivery>
      <VehicleActivity>
        <RecordedAtTime>2026-04-09T12:00:00+00:00</RecordedAtTime>
        <MonitoredVehicleJourney>
          <OperatorRef>BODSREF</OperatorRef>
          <VehicleRef>BODSREF-1001</VehicleRef>
          <PublishedLineName>7</PublishedLineName>
          <DestinationName>Town Centre</DestinationName>
          <VehicleLocation>
            <Longitude>-1.234</Longitude>
            <Latitude>52.345</Latitude>
          </VehicleLocation>
          <Bearing>90</Bearing>
        </MonitoredVehicleJourney>
      </VehicleActivity>
    </VehicleMonitoringDelivery>
  </ServiceDelivery>
</Siri>
"""
        response.raise_for_status = Mock()

        redis_client = Mock()
        redis_client.sunion.return_value = []

        with patch("vehicles.views.redis_client", redis_client), patch(
            "vehicles.views.requests.get", return_value=response
        ) as mock_get:
            result = self.client.get("/vehicles.json?operator=TST1")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json(),
            [
                {
                    "id": 577164854,
                    "coordinates": [-1.234, 52.345],
                    "datetime": "2026-04-09T12:00:00+00:00",
                    "destination": "Town Centre",
                    "vehicle": {"name": "1001"},
                    "heading": 90.0,
                    "service": {"line_name": "7"},
                }
            ],
        )
        mock_get.assert_called_once()
        self.assertEqual(
            mock_get.call_args.kwargs["params"], {"api_key": "test-bods-key"}
        )
