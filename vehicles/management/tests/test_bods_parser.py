import io
import zipfile

from django.test import SimpleTestCase

from vehicles.realtime import bods_parser


SIRI_XML = b"""
<Siri xmlns="http://www.siri.org.uk/siri" version="2.0">
  <ServiceDelivery>
    <ResponseTimestamp>2026-04-09T12:00:00+00:00</ResponseTimestamp>
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
        </MonitoredVehicleJourney>
      </VehicleActivity>
      <VehicleActivity>
        <RecordedAtTime>2026-04-09T12:01:00+00:00</RecordedAtTime>
        <MonitoredVehicleJourney>
          <OperatorRef>BODSREF</OperatorRef>
          <VehicleRef>BODSREF-1002</VehicleRef>
        </MonitoredVehicleJourney>
      </VehicleActivity>
    </VehicleMonitoringDelivery>
  </ServiceDelivery>
</Siri>
"""


class BodsParserTests(SimpleTestCase):
    def test_parse_vehicle_activity_xml_returns_activity_dicts(self):
        root, items = bods_parser.parse_vehicle_activity_xml(SIRI_XML)

        self.assertEqual(root.tag, f"{{{bods_parser.SIRI_NS}}}Siri")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["MonitoredVehicleJourney"]["OperatorRef"], "BODSREF")
        self.assertEqual(items[0]["MonitoredVehicleJourney"]["VehicleRef"], "BODSREF-1001")

    def test_maybe_unzip_payload_handles_zip_content(self):
        zipped = io.BytesIO()
        with zipfile.ZipFile(zipped, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("vm.xml", SIRI_XML)

        data = bods_parser.maybe_unzip_payload(
            zipped.getvalue(), content_type="application/zip"
        )
        self.assertEqual(data.strip(), SIRI_XML.strip())

    def test_elem_to_dict_preserves_repeated_xml_keys_as_list(self):
        node = bods_parser.etree.fromstring(
            b"""
<Parent>
  <Child>a</Child>
  <Child>b</Child>
</Parent>
"""
        )
        result = bods_parser.elem_to_dict(node)
        self.assertEqual(result["Child"], ["a", "b"])
