"""Tests for the Darwin (National Rail) importer.

The XML fixtures are trimmed versions of real Push Port v16 messages.
"""

import json
from datetime import date
from unittest import mock

import fakeredis
import time_machine
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from vehicles.darwin.messages import parse_pport
from vehicles.darwin.position import (
    get_delay,
    interpolate_position,
    point_datetime,
)
from vehicles.darwin.state import DarwinState

PPORT_NS = 'xmlns="http://www.thalesgroup.com/rtti/PushPort/v16" ' \
    'xmlns:ns2="http://www.thalesgroup.com/rtti/PushPort/Schedules/v3" ' \
    'xmlns:ns5="http://www.thalesgroup.com/rtti/PushPort/Forecasts/v3"'

SCHEDULE_XML = f"""<?xml version="1.0"?>
<Pport {PPORT_NS} ts="2026-11-10T20:16:01Z" version="16.0">
  <uR updateOrigin="Workstation">
    <schedule rid="202611107189015" uid="G89015" trainId="1B41"
              ssd="2026-11-10" toc="NT" trainCat="XX">
      <ns2:OR wtd="19:24" ptd="19:24" tpl="YORK" act="TB"/>
      <ns2:IP wta="19:34:30" wtd="19:35:30" tpl="CHFN" act="T " pta="19:35" ptd="19:35"/>
      <ns2:PP wtp="19:41" tpl="MCKLFLD"/>
      <ns2:IP wta="19:43:30" wtd="19:44:30" tpl="GARFRTH" act="T " pta="19:44" ptd="19:44"/>
      <ns2:IP wta="20:07:30" wtd="20:08:30" tpl="NPUD" act="T " pta="20:08" ptd="20:08"/>
      <ns2:IP wta="20:16" wtd="20:19:30" tpl="BRADIN" act="T RM" pta="20:16" ptd="20:19"/>
      <ns2:DT wta="20:01" tpl="LVRPLSH" act="TF" pta="20:01"/>
    </schedule>
  </uR>
</Pport>"""

TS_XML = f"""<?xml version="1.0"?>
<Pport {PPORT_NS} ts="2026-11-10T20:16:01Z" version="16.0">
  <uR updateOrigin="Workstation">
    <TS rid="202611107189015" uid="G89015" ssd="2026-11-10">
      <ns5:LateReason>535</ns5:LateReason>
      <ns5:Location tpl="YORK" wtd="19:24" ptd="19:24">
        <ns5:dep at="19:24" atClass="Automatic" src="TD"/>
        <ns5:plat platsrc="A">7</ns5:plat>
        <ns5:length>3</ns5:length>
      </ns5:Location>
      <ns5:Location tpl="CHFN" wta="19:34:30" wtd="19:35:30" pta="19:35" ptd="19:35">
        <ns5:arr at="19:34" atClass="Automatic" src="TRUST"/>
        <ns5:dep at="19:35" atClass="Automatic" src="TRUST"/>
        <ns5:plat>3</ns5:plat>
      </ns5:Location>
      <ns5:Location tpl="NPUD" wta="20:07:30" wtd="20:08:30" pta="20:08" ptd="20:08">
        <ns5:arr et="20:17" src="Darwin"/>
        <ns5:dep et="20:18" src="Darwin"/>
        <ns5:plat>1</ns5:plat>
      </ns5:Location>
      <ns5:Location tpl="LVRPLSH" wta="20:01">
        <ns5:arr et="20:30" src="Darwin"/>
      </ns5:Location>
    </TS>
  </uR>
</Pport>"""

FORMATION_XML = f"""<?xml version="1.0"?>
<Pport {PPORT_NS} ts="2026-11-10T20:17:35Z" version="16.0">
  <uR updateOrigin="CIS">
    <scheduleFormations rid="202611107189015">
      <ns4:formation fid="202611107189015-001" xmlns:ns4="http://www.thalesgroup.com/rtti/PushPort/Formations/v2">
        <ns4:coaches>
          <ns4:coach coachNumber="1" coachClass="Standard"/>
          <ns4:coach coachNumber="2" coachClass="Standard"/>
        </ns4:coaches>
      </ns4:formation>
    </scheduleFormations>
  </uR>
</Pport>"""

FORMATION_STOCK_XML = f"""<?xml version="1.0"?>
<Pport {PPORT_NS} ts="2026-11-10T20:17:35Z" version="16.0">
  <uR updateOrigin="CIS">
    <scheduleFormations rid="202611107189015">
      <ns4:formation fid="202611107189015-001" xmlns:ns4="http://www.thalesgroup.com/rtti/PushPort/Formations/v2">
        <ns4:coaches>
          <ns4:coach coachNumber="1" coachClass="Standard" stockNumber="87001"/>
        </ns4:coaches>
      </ns4:formation>
    </scheduleFormations>
  </uR>
</Pport>"""

CANCELLED_XML = f"""<?xml version="1.0"?>
<Pport {PPORT_NS} ts="2026-11-10T20:16:17Z" version="16.0">
  <uR updateOrigin="CIS">
    <schedule rid="202611107189015" uid="G89015" trainId="1B41"
              ssd="2026-11-10" toc="NT" trainCat="XX">
      <ns2:OR wtd="19:24" ptd="19:24" tpl="YORK" act="TB" can="true"/>
      <ns2:cancelReason>811</ns2:cancelReason>
    </schedule>
  </uR>
</Pport>"""

NON_PASSENGER_XML = f"""<?xml version="1.0"?>
<Pport {PPORT_NS} ts="2026-11-10T20:16:00Z" version="16.0">
  <uR updateOrigin="Darwin">
    <schedule rid="202611117637879" uid="L37879" trainId="5R69"
              ssd="2026-11-11" toc="CH" trainCat="EE" isPassengerSvc="false">
      <ns2:OPOR wtd="00:16" tpl="BHAMMRS" act="TB"/>
      <ns2:OPDT wta="00:18" tpl="BHAMMSS" act="TF"/>
    </schedule>
  </uR>
</Pport>"""


def coords_for(points):
    return {p["tpl"]: (i * 0.01, 51.5 + i * 0.005) for i, p in enumerate(points)}


class DarwinParseTest(SimpleTestCase):
    def test_parse_schedule(self):
        updates = parse_pport(SCHEDULE_XML.encode())
        self.assertEqual(len(updates), 1)
        schedule = updates[0]
        self.assertEqual(schedule["kind"], "schedule")
        self.assertEqual(schedule["rid"], "202611107189015")
        self.assertEqual(schedule["headcode"], "1B41")
        self.assertEqual(schedule["toc"], "NT")
        self.assertEqual(schedule["ssd"], "2026-11-10")
        self.assertTrue(schedule["is_passenger"])
        self.assertFalse(schedule["cancelled"])
        types = [p["type"] for p in schedule["points"]]
        self.assertEqual(types[0], "origin")
        self.assertEqual(types[-1], "destination")
        self.assertIn("call", types)
        self.assertIn("pass", types)

    def test_parse_ts(self):
        updates = parse_pport(TS_XML.encode())
        ts = updates[0]
        self.assertEqual(ts["kind"], "ts")
        self.assertEqual(ts["late_reason"], "535")
        york = ts["locations"][0]
        self.assertEqual(york["tpl"], "YORK")
        self.assertEqual(york["dep_at"], "19:24:00")
        self.assertEqual(york["platform"], "7")
        self.assertEqual(york["length"], 3)
        npud = ts["locations"][2]
        self.assertEqual(npud["arr_et"], "20:17:00")
        self.assertEqual(npud["dep_et"], "20:18:00")

    def test_parse_formation(self):
        updates = parse_pport(FORMATION_XML.encode())
        self.assertEqual(updates[0]["kind"], "formation")
        self.assertEqual(len(updates[0]["coaches"]), 2)

    def test_parse_cancelled(self):
        updates = parse_pport(CANCELLED_XML.encode())
        self.assertTrue(updates[0]["cancelled"])
        self.assertEqual(updates[0]["cancel_reason"], "811")

    def test_parse_non_passenger(self):
        updates = parse_pport(NON_PASSENGER_XML.encode())
        self.assertFalse(updates[0]["is_passenger"])
        # OPOR/OPDT aren't passenger calling points - ignored
        self.assertEqual(updates[0]["points"], [])

    def test_garbage(self):
        self.assertEqual(parse_pport(b"not xml"), [])
        self.assertEqual(parse_pport(b"<foo/>"), [])


class DarwinStateTest(SimpleTestCase):
    def test_merge_schedule_and_ts(self):
        state = DarwinState()
        for xml in (SCHEDULE_XML, TS_XML):
            for update in parse_pport(xml.encode()):
                state.apply(update)

        service = state.services["202611107189015"]
        self.assertEqual(service.headcode, "1B41")
        self.assertEqual(service.toc, "NT")
        self.assertEqual(service.late_reason, "535")

        points = service.merged_points()
        self.assertEqual(len(points), 7)

        york = points[0]
        self.assertEqual(york["tpl"], "YORK")
        self.assertEqual(york["dep_at"], "19:24:00")
        self.assertEqual(york["platform"], "7")

        npud = next(p for p in points if p["tpl"] == "NPUD")
        self.assertEqual(npud["arr_et"], "20:17:00")
        # public times survive from the schedule
        self.assertEqual(npud["pta"], "20:08:00")

        # a point not covered by the TS keeps schedule times only
        bradin = next(p for p in points if p["tpl"] == "BRADIN")
        self.assertNotIn("arr_at", bradin)
        self.assertEqual(bradin["pta"], "20:16:00")

    def test_signature_changes(self):
        state = DarwinState()
        for update in parse_pport(SCHEDULE_XML.encode()):
            state.apply(update)
        sig1 = state.services["202611107189015"].signature()
        for update in parse_pport(TS_XML.encode()):
            state.apply(update)
        sig2 = state.services["202611107189015"].signature()
        self.assertNotEqual(sig1, sig2)


class DarwinPositionTest(SimpleTestCase):
    ssd = date(2026, 11, 10)

    def _points(self):
        state = DarwinState()
        for xml in (SCHEDULE_XML, TS_XML):
            for update in parse_pport(xml.encode()):
                state.apply(update)
        return state.services["202611107189015"].merged_points()

    def test_interpolate_mid_segment(self):
        points = self._points()
        coords = coords_for(points)
        # between CHFN dep 19:35 and MCKLFLD pass 19:41 - use 19:38
        now = point_datetime(self.ssd, "19:38")
        result = interpolate_position(points, self.ssd, now, lambda t: coords.get(t))
        self.assertIsNotNone(result)
        # ~ halfway between index 1 (CHFN) and 2 (MCKLFLD)
        self.assertAlmostEqual(result["fraction"], 0.5, delta=0.2)
        self.assertEqual(result["prev_tpl"], "CHFN")
        self.assertEqual(result["next_tpl"], "MCKLFLD")
        self.assertIsNotNone(result["heading"])

    def test_interpolate_uses_expected_times(self):
        points = self._points()
        coords = coords_for(points)
        # NPUD arr expected 20:17 vs public 20:08 - at 20:10 the train should
        # still be well before NPUD
        now = point_datetime(self.ssd, "20:10")
        result = interpolate_position(points, self.ssd, now, lambda t: coords.get(t))
        self.assertIsNotNone(result)
        self.assertLess(result["fraction"], 0.9)

    def test_before_origin_and_after_destination(self):
        points = self._points()
        coords = coords_for(points)
        early = interpolate_position(
            points, self.ssd, point_datetime(self.ssd, "19:00"), lambda t: coords.get(t)
        )
        self.assertEqual(early["prev_tpl"], None)
        self.assertEqual(early["next_tpl"], "YORK")

        late = interpolate_position(
            points, self.ssd, point_datetime(self.ssd, "22:00"), lambda t: coords.get(t)
        )
        self.assertEqual(late["prev_tpl"], "LVRPLSH")
        self.assertEqual(late["next_tpl"], None)

    def test_no_coords_returns_none_or_partial(self):
        points = self._points()
        # only give coords to two points - interpolation happens between them
        coords = {"CHFN": (0.0, 51.0), "NPUD": (0.1, 51.1)}
        now = point_datetime(self.ssd, "19:38")
        result = interpolate_position(points, self.ssd, now, lambda t: coords.get(t))
        self.assertIsNotNone(result)
        self.assertEqual(result["prev_tpl"], "CHFN")
        self.assertEqual(result["next_tpl"], "NPUD")
        self.assertGreater(result["coord"][0], 0.0)
        self.assertLess(result["coord"][0], 0.1)

    def test_delay_vs_public(self):
        points = self._points()
        # NPUD expected arr 20:17 vs public 20:08 -> ~9 min late approaching it
        now = point_datetime(self.ssd, "20:10")
        delay = get_delay(points, self.ssd, now)
        self.assertIsNotNone(delay)
        self.assertGreater(delay.total_seconds(), 0)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class DarwinCommandTest(TestCase):
    """import_darwin command: journey creation, redis output, vehicle attach"""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.gis.geos import GEOSGeometry

        from busstops.models import DataSource, Operator, OperatorCode, StopPoint

        cls.source = DataSource.objects.create(name="Darwin")
        cls.operator = Operator.objects.create(noc="NT", name="Northern")
        OperatorCode.objects.create(
            source=cls.source, code="NT", operator=cls.operator
        )

        def stop(atco, name, tpl, lon, lat):
            StopPoint.objects.create(
                atco_code=atco,
                common_name=name,
                latlong=GEOSGeometry(f"SRID=4326;POINT({lon} {lat})"),
                tiploc=tpl,
            )

        stop("9100YORK", "York", "YORK", -1.08, 53.96)
        stop("9100CHFN", "Christchurch", "CHFN", -1.52, 53.75)
        stop("9100NPUD", "Napier", "NPUD", -1.95, 53.55)
        stop("9100LVRPLSH", "Liverpool Street", "LVRPLSH", -0.08, 51.52)

    def setUp(self):
        from vehicles.management.commands.import_darwin import Command

        self.redis = fakeredis.FakeStrictRedis(version=7)
        self.command = Command()
        self.command.source = self.source
        self.command.reference = {
            "locations": {},
            "tocs": {"NT": "Northern"},
        }
        from vehicles.darwin.tiploc import TiplocResolver
        self.command.resolver = TiplocResolver(self.command.reference)
        self.command.state = DarwinState()
        self.command.operators = {}
        self.command.journeys = {}
        self.command.signatures = {}
        self.command.operator_codes = {}
        # fixtures use ssd 2026-11-10 - freeze "now" inside the service window
        # and skip the once-daily state prune
        self.traveller = time_machine.travel(
            "2026-11-10T20:30:00+01:00", tick=False
        )
        self.traveller.start()
        self.command._last_prune = timezone.localdate()

    def tearDown(self):
        self.traveller.stop()

    def _feed(self, *xmls):
        for xml in xmls:
            for update in parse_pport(xml.encode()):
                self.command.state.apply(update)

    def _flush(self):
        self.command.signatures = {}
        self.command.flush()

    @mock.patch("vehicles.management.commands.import_darwin.redis_client")
    def test_journey_only_tracking(self, mock_redis):
        mock_redis.return_value = self.redis
        self._feed(SCHEDULE_XML, TS_XML)
        self._flush()

        from vehicles.models import VehicleJourney

        journey = VehicleJourney.objects.get(code="202611107189015")
        self.assertEqual(journey.route_name, "1B41")
        self.assertEqual(journey.operator, self.operator)
        self.assertIsNone(journey.vehicle)
        self.assertEqual(journey.destination, "Liverpool Street")

        # tracked under negative journey id
        redis_key = f"vehicle{-journey.id}"
        item = json.loads(self.redis.get(redis_key))
        self.assertEqual(item["journey_id"], journey.id)
        self.assertEqual(item["service"]["line_name"], "1B41")
        self.assertEqual(item["destination"], "Liverpool Street")
        self.assertIn("vehicle", item)
        self.assertEqual(item["vehicle"]["features"], "train")

        # in the operator's live set and geo index
        self.assertIn(
            str(-journey.id),
            {m.decode() for m in self.redis.smembers(f"operator{self.operator.noc}vehicles")},
        )

    @mock.patch("vehicles.management.commands.import_darwin.redis_client")
    def test_vehicle_attach_from_formation(self, mock_redis):
        mock_redis.return_value = self.redis
        self._feed(SCHEDULE_XML, TS_XML)
        self._flush()

        from vehicles.models import Vehicle, VehicleJourney

        journey = VehicleJourney.objects.get(code="202611107189015")
        self.assertIsNone(journey.vehicle)
        negative_key = f"vehicle{-journey.id}"
        self.assertIsNotNone(self.redis.get(negative_key))

        # formation arrives later with a unit number - journey adopts it
        self._feed(FORMATION_STOCK_XML)
        self._flush()

        journey.refresh_from_db()
        self.assertIsNotNone(journey.vehicle)
        self.assertEqual(journey.vehicle.code, "NT:87001")
        self.assertEqual(journey.vehicle.operator, self.operator)
        self.assertEqual(journey.vehicle.vehicle_type.name, "train")

        # now tracked under the positive vehicle id; stale negative key gone
        self.assertIsNone(self.redis.get(negative_key))
        item = json.loads(self.redis.get(f"vehicle{journey.vehicle.id}"))
        self.assertEqual(item["journey_id"], journey.id)

    @mock.patch("vehicles.management.commands.import_darwin.redis_client")
    def test_cancelled_not_tracked(self, mock_redis):
        mock_redis.return_value = self.redis
        self._feed(SCHEDULE_XML, TS_XML, CANCELLED_XML)
        self._flush()

        from vehicles.models import VehicleJourney
        self.assertFalse(
            VehicleJourney.objects.filter(code="202611107189015").exists()
        )

    @mock.patch("vehicles.management.commands.import_darwin.redis_client")
    def test_non_passenger_not_tracked(self, mock_redis):
        mock_redis.return_value = self.redis
        self._feed(NON_PASSENGER_XML)
        self._flush()
        self.assertEqual(self.redis.keys("vehicle*"), [])
