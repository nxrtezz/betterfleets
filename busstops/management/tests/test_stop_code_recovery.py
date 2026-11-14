from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from django.core.management import call_command
from django.test import TestCase, override_settings
from busstops.models import DataSource, StopPoint
from bustimes.management.commands.import_transxchange import Command


class StopCodeRecoveryTest(TestCase):
    def test_official_alias_fills_native_and_scoped_stops_without_overwriting(self):
        native=StopPoint.objects.create(atco_code='6200001',active=True)
        scoped=StopPoint.objects.create(atco_code='123:6200001',active=True)
        existing=StopPoint.objects.create(atco_code='456:6200001',active=True,naptan_code='existing')
        unrelated=StopPoint.objects.create(atco_code='6200002',active=True)
        with TemporaryDirectory() as directory, override_settings(DATA_DIR=Path(directory)):
            path=Path(directory)/'naptan.xml'
            path.write_text('<NaPTAN xmlns="http://www.naptan.org.uk/"><StopPoints><StopPoint><AtcoCode>6200001</AtcoCode><NaptanCode>36237242</NaptanCode></StopPoint></StopPoints></NaPTAN>')
            call_command('backfill_stop_codes',path,stdout=StringIO())
            native.refresh_from_db()
            self.assertIsNone(native.naptan_code)
            call_command('backfill_stop_codes',path,apply=True,stdout=StringIO())
        native.refresh_from_db();scoped.refresh_from_db();existing.refresh_from_db();unrelated.refresh_from_db()
        self.assertEqual(native.naptan_code,'36237242')
        self.assertEqual(scoped.naptan_code,'36237242')
        self.assertEqual(existing.naptan_code,'existing')
        self.assertIsNone(unrelated.naptan_code)

    def test_timetable_reimport_preserves_recovered_short_code(self):
        source=DataSource.objects.create(name='S')
        stop=StopPoint.objects.create(atco_code=f'{source.pk}:6200001',active=True,naptan_code='36237242')
        command=Command();command.source=source;command.region_id='S'
        command.do_stops({'6200001':SimpleNamespace(element=ET.fromstring('<StopPoint Status="active"><Descriptor><CommonName>Test</CommonName></Descriptor></StopPoint>'))})
        stop.refresh_from_db()
        self.assertEqual(stop.naptan_code,'36237242')
