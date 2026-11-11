"""National Rail live trains via the Signalbox map API.

Polls https://map-api.production.signalbox.io/api/locations for every
live train's position, enriches new services via /api/train-information,
and mirrors them into the same Redis structures as the other importers.

This is an unofficial third-party API - import_darwin is the licensed
fallback covering the same ground.

Unit/stock numbers aren't in either feed for open-data accounts, so
rolling stock allocations are enriched separately via the RTT API
(vehicles/rtt.py) using the Darwin uid that train-information provides.
"""

import os

# playwright's sync API runs under anyio, which makes Django's async
# detection think ORM calls are unsafe - they aren't, it's a worker thread
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")

import heapq
import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.db import IntegrityError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from redis.exceptions import ConnectionError

from busstops.models import DataSource
from vehicles.darwin.operators import get_operator, get_toc_name
from vehicles.models import (
    Vehicle,
    VehicleCode,
    VehicleJourney,
    VehicleLocation,
    VehicleType,
)
from vehicles.rtt import (
    RttClient,
    RttError,
    allocation_summary,
    tops_display_name,
)
from vehicles.utils import (
    VEHICLE_POSITIONS_CHANNEL,
    append_status,
    get_operator_livery,
    redis_client,
)

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get(
    "SIGNALBOX_API_BASE", "https://map-api.production.signalbox.io"
)
POLL_INTERVAL = 30  # seconds between /api/locations polls
INFO_CACHE_SIZE = 6000
INFO_FETCH_BATCH = 15  # max train-information lookups per poll
INFO_FETCH_WORKERS = 3
RTT_LOOKUP_INTERVAL = 37  # ~97/hour, under the 100/hour plan limit
SCRAPE_RETRY_SECONDS = 1200  # wait before re-scraping a journey
SCRAPE_MIN_INTERVAL = 10  # seconds between page loads (politeness)
RTT_SERVICE_URL = "https://www.realtimetrains.co.uk/service/gb-nr:{uid}/{date}/detailed"
STATE_RETENTION_DAYS = 2


def _fetch(path: str) -> dict | list | None:
    req = urllib.request.Request(
        BASE_URL + path, headers={"User-Agent": "betterfleets/1.0"}
    )
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning("signalbox %s failed: %s", path, e)
        return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parse_datetime(value)
    except (ValueError, TypeError):
        return None


class Command(BaseCommand):
    source_name = "Signalbox"
    wait = POLL_INTERVAL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = None
        self.rtt_source = None
        self.journeys: dict[str, VehicleJourney] = {}
        self.infos: dict[str, dict] = {}
        self.operators = {}
        self.rtt = RttClient()
        # heap of (-departure_ts, uid, journey): most recent departures first
        self.rtt_heap: list = []
        self.rtt_queued: set[str] = set()
        self.rtt_retries: dict[str, int] = {}
        self._rtt_next = 0.0
        # playwright scraper fallback for journeys past halfway without a unit
        self.scrape_queue: queue.Queue = queue.Queue()
        self.scrape_eligible: dict[int, float] = {}
        self._class_cache: dict[str, str | None] = {}
        self._pending_writes = []
        self._pending_appendages = []
        self._last_positions: dict[str, tuple[float, float]] = {}

    def do_source(self):
        self.source, _ = DataSource.objects.get_or_create(
            name=self.source_name,
            defaults={"url": BASE_URL},
        )
        self.rtt_source, _ = DataSource.objects.get_or_create(
            name="RTT",
            defaults={"url": "https://realtimetrains.co.uk/"},
        )
        return self

    # -- journey / info ----------------------------------------------------

    def get_operator_for(self, toc: str | None, name: str | None):
        if not toc:
            return None
        toc_name = get_toc_name(toc, None) or name
        return get_operator(toc, toc_name, self.source, self.operators)

    def get_journey(self, rid: str, info: dict) -> VehicleJourney:
        if rid in self.journeys:
            return self.journeys[rid]

        journey = VehicleJourney.objects.filter(
            code=rid, source=self.source
        ).first()
        if journey is None:
            dep = _parse_iso(info.get("origin_departure"))
            journey_datetime = dep or timezone.now()
            # service date in UK time - origin_departure is UTC and can
            # cross midnight
            service_date = journey_datetime.astimezone(
                ZoneInfo("Europe/London")
            ).date()
            journey = VehicleJourney(
                datetime=journey_datetime,
                date=service_date,
                route_name=info.get("headcode") or "",
                code=rid,
                destination=info.get("destination_name") or "",
                source=self.source,
                operator=self.get_operator_for(
                    info.get("toc_code"), info.get("train_operator")
                ),
                data={
                    "uid": info.get("uid"),
                    "toc": info.get("toc_code"),
                    "headcode": info.get("headcode"),
                    "train_operator": info.get("train_operator"),
                    "origin_crs": info.get("origin_crs"),
                    "origin_name": info.get("origin_name"),
                    "destination_crs": info.get("destination_crs"),
                    "stops": info.get("stops"),
                },
            )
            journey.save()
            self._queue_rtt(journey)

        self.journeys[rid] = journey
        return journey

    # -- RTT rolling stock enrichment --------------------------------------

    def _queue_rtt(self, journey: VehicleJourney):
        if not self.rtt.configured:
            return
        data = journey.data or {}
        uid = data.get("uid")
        if not uid or uid in self.rtt_queued or journey.vehicle_id:
            return
        self.rtt_queued.add(uid)
        departed = journey.datetime or timezone.now()
        heapq.heappush(
            self.rtt_heap,
            (-departed.timestamp(), uid, journey),
        )

    def _process_rtt(self):
        if not self.rtt_heap or time.time() < self._rtt_next:
            return
        self._rtt_next = time.time() + RTT_LOOKUP_INTERVAL
        _, uid, journey = heapq.heappop(self.rtt_heap)
        try:
            service = self.rtt.service(uid, journey.date.isoformat())
        except RttError as e:
            logger.warning("rtt lookup failed for %s: %s", uid, e)
            # retry once - transient failures shouldn't lose the unit
            if self.rtt_retries.get(uid, 0) < 1:
                self.rtt_retries[uid] = self.rtt_retries.get(uid, 0) + 1
                departed = journey.datetime or timezone.now()
                heapq.heappush(
                    self.rtt_heap,
                    (-departed.timestamp(), uid, journey),
                )
            return
        self._apply_rtt(journey, service)

    def _apply_rtt(self, journey: VehicleJourney, service: dict):
        summary = allocation_summary(service)
        if summary is None:
            return
        units = summary.get("units") or []
        tops = summary["tops"]
        leading_class = summary["leading_class"]

        journey.data = journey.data or {}
        journey.data["rtt"] = summary
        update_fields = ["data"]

        # ensure a Vehicle exists for every unit in the formation
        vehicles = []
        for unit in units:
            vehicle = self.get_rtt_vehicle(
                unit["tops"], leading_class, journey
            )
            if vehicle:
                vehicles.append(vehicle)

        if tops and not journey.vehicle_id and vehicles:
            vehicle = vehicles[0]
            old_negative_key = f"vehicle{-journey.id}"
            journey.vehicle = vehicle
            update_fields.append("vehicle")
            if vehicle.latest_journey_id != journey.id:
                vehicle.latest_journey = journey
                vehicle.save(update_fields=["latest_journey"])
            if redis_client:
                try:
                    redis_client.delete(old_negative_key)
                except ConnectionError:
                    pass

        journey.save(update_fields=update_fields)

    def get_rtt_vehicle(
        self, tops: str, leading_class: str | None, journey: VehicleJourney
    ) -> Vehicle | None:
        # uniqueness is (upper(code), operator) - the same TOPS can be
        # reported for more than one service, so look up by both
        vehicle = (
            Vehicle.objects.filter(
                code__iexact=tops, operator=journey.operator
            )
            .select_related("operator")
            .first()
        )
        if vehicle is None and journey.operator_id is None:
            vehicle = Vehicle.objects.filter(
                source=self.rtt_source, code__iexact=tops, operator__isnull=True
            ).first()
        if vehicle:
            if not vehicle.operator_id and journey.operator_id:
                vehicle.operator = journey.operator
                vehicle.save(update_fields=["operator"])
            return vehicle

        suffix = journey.operator.noc if journey.operator_id else "x"
        vehicle = Vehicle(
            slug=f"rtt-{tops}-{suffix}",
            code=tops,
            fleet_number=int(tops) if tops.isdigit() else None,
            fleet_code=tops_display_name(tops, leading_class),
            operator=journey.operator,
            source=self.rtt_source,
        )
        vehicle_type, _ = VehicleType.objects.get_or_create(
            name="train", defaults={"style": "train"}
        )
        vehicle.vehicle_type = vehicle_type
        try:
            vehicle.save()
        except IntegrityError:
            # lost a race with another journey for the same unit
            return Vehicle.objects.filter(
                code__iexact=tops, operator=journey.operator
            ).first()
        VehicleCode.objects.get_or_create(
            vehicle=vehicle, scheme="TOPS", code=tops
        )
        return vehicle

    # -- playwright scraper fallback ----------------------------------------

    @staticmethod
    def _stop_time(stop: dict) -> datetime | None:
        for key in (
            "actual_arrival",
            "arrival",
            "actual_departure",
            "departure",
        ):
            parsed = _parse_iso(stop.get(key))
            if parsed:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
                return parsed
        return None

    def _past_halfway(self, journey: VehicleJourney, now: datetime) -> bool:
        stops = (journey.data or {}).get("stops") or []
        if len(stops) < 4:
            return False
        passed = 0
        for stop in stops:
            stop_time = self._stop_time(stop)
            if stop_time is None:
                continue
            if stop_time <= now:
                passed += 1
            else:
                break
        return passed >= len(stops) / 2

    def _check_scrape_candidates(self, live_rids: set):
        now = timezone.now()
        now_ts = now.timestamp()
        for rid, journey in self.journeys.items():
            if (
                rid not in live_rids
                or journey.vehicle_id
                or (
                    journey.id in self.scrape_eligible
                    and now_ts < self.scrape_eligible[journey.id]
                )
            ):
                continue
            if not self._past_halfway(journey, now):
                continue
            self.scrape_eligible[journey.id] = now_ts + 300
            self.scrape_queue.put(journey.id)

    def _guess_class(self, tops: str) -> str | None:
        if tops in self._class_cache:
            return self._class_cache[tops]
        guess = None
        for length in (3, 2):
            prefix = tops[:length]
            if VehicleType.objects.filter(name=f"Class {prefix}").exists():
                guess = prefix
                break
        self._class_cache[tops] = guess
        return guess

    def _scrape_worker(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("playwright not installed - scrape fallback disabled")
            return
        from django.db import close_old_connections

        close_old_connections()
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        )
        while True:
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(user_agent=user_agent)
                    while True:
                        try:
                            journey_id = self.scrape_queue.get(timeout=300)
                        except queue.Empty:
                            continue
                        try:
                            self._scrape_one(page, journey_id)
                        except Exception:
                            logger.exception(
                                "rtt scrape failed for journey %s", journey_id
                            )
                        finally:
                            self.scrape_eligible[journey_id] = (
                                time.time() + SCRAPE_RETRY_SECONDS
                            )
                            time.sleep(SCRAPE_MIN_INTERVAL)
            except Exception:
                logger.exception("rtt scrape worker error - restarting in 60s")
                time.sleep(60)

    def _scrape_one(self, page, journey_id: int):
        journey = (
            VehicleJourney.objects.select_related("operator")
            .filter(id=journey_id)
            .first()
        )
        if journey is None or journey.vehicle_id:
            return
        uid = (journey.data or {}).get("uid")
        if not uid:
            return
        url = RTT_SERVICE_URL.format(uid=uid, date=journey.date.isoformat())
        page.goto(url, timeout=90000)
        # the Anubis browser check redirects automatically - wait for content
        try:
            page.wait_for_selector(
                ".additionaldata, .service, h1", timeout=45000
            )
        except Exception:
            pass
        page.wait_for_timeout(1500)
        html = page.content()
        identities = [
            i.strip()
            for i in re.findall(r'class="identity"[^>]*>\s*([^<]+?)\s*<', html)
            if i.strip()
        ]
        if not identities:
            logger.info("rtt scrape: no units found for uid %s", uid)
            return
        self._attach_scraped_units(journey, identities)

    def _attach_scraped_units(self, journey: VehicleJourney, identities: list):
        vehicles = []
        for tops in identities:
            vehicle = self.get_rtt_vehicle(tops, self._guess_class(tops), journey)
            if vehicle:
                vehicles.append(vehicle)
        if not vehicles or journey.vehicle_id:
            return
        vehicle = vehicles[0]
        journey.vehicle = vehicle
        journey.data = journey.data or {}
        journey.data["rtt_scrape"] = {"tops": identities}
        journey.save(update_fields=["vehicle", "data"])
        if vehicle.latest_journey_id != journey.id:
            vehicle.latest_journey = journey
            vehicle.save(update_fields=["latest_journey"])
        if redis_client:
            try:
                redis_client.delete(f"vehicle{-journey.id}")
            except ConnectionError:
                pass
        logger.info(
            "rtt scrape: attached %s to journey %s", identities, journey.id
        )

    # -- locations / redis ---------------------------------------------------

    def _stops_context(self, info: dict, now: datetime):
        """nearest previous/next calling point names for the map popup"""
        prev_stop = next_stop = None
        for stop in info.get("stops") or []:
            when = _parse_iso(stop.get("departure") or stop.get("arrival"))
            if when is None:
                continue
            if when <= now:
                prev_stop = stop.get("name")
            else:
                next_stop = stop.get("name")
                break
        return prev_stop, next_stop

    def create_location(self, rid: str, journey: VehicleJourney, train: dict):
        pos = train.get("location") or train.get("predicted_location") or {}
        try:
            lon, lat = float(pos["lon"]), float(pos["lat"])
        except (KeyError, TypeError, ValueError):
            return None

        now = timezone.now()
        info = self.infos.get(rid) or {}
        prev_stop, next_stop = self._stops_context(info, now)

        heading = self._heading(rid, lon, lat)

        location = VehicleLocation(
            latlong=Point(lon, lat, srid=4326),
            heading=heading,
            delay=timedelta(minutes=train.get("delay") or 0),
            prev_stop=prev_stop,
            next_stop=next_stop,
        )
        location.datetime = now
        location.journey = journey
        return location

    @staticmethod
    def _bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        import math

        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dlam = math.radians(lon2 - lon1)
        y = math.sin(dlam) * math.cos(phi2)
        x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
        return (math.degrees(math.atan2(y, x)) + 360) % 360

    def _heading(self, rid: str, lon: float, lat: float) -> float | None:
        """bearing from the previous poll's position for this rid"""
        prev = self._last_positions.get(rid)
        self._last_positions[rid] = (lon, lat)
        if len(self._last_positions) > 20000:
            for key in list(self._last_positions)[:5000]:
                del self._last_positions[key]
        if prev is None or prev == (lon, lat):
            return None
        return self._bearing(prev[0], prev[1], lon, lat)

    def _redis_json(self, location, journey, vehicle, info) -> dict:
        redis_json = location.get_redis_json()
        redis_json["rid"] = journey.code

        if vehicle is None:
            name = " ".join(
                part
                for part in (
                    info.get("headcode"),
                    info.get("train_operator"),
                )
                if part
            )
            vehicle_json = {
                "name": name or journey.route_name or "Train",
                "features": "train",
            }
            # no unit assigned yet - show the operator's most common livery
            if livery_id := get_operator_livery(journey.operator):
                vehicle_json["livery"] = livery_id
            redis_json["vehicle"] = vehicle_json
        if info.get("toc_code"):
            redis_json.setdefault("service", {})["toc"] = info["toc_code"]
        return redis_json

    def queue_redis_write(self, location, journey, vehicle, info):
        self._pending_writes.append((location, journey, vehicle, info))
        self._pending_appendages.append(
            (
                journey.get_redis_key(),
                int(location.datetime.timestamp()),
                location.latlong.x,
                location.latlong.y,
            )
        )

    def flush_redis(self):
        from asgiref.sync import async_to_sync
        from channels.exceptions import ChannelFull
        from channels.layers import get_channel_layer

        if not self._pending_writes:
            return
        if redis_client:
            try:
                pipeline = redis_client.pipeline(transaction=False)
                for location, journey, vehicle, info in self._pending_writes:
                    redis_json = json.dumps(
                        self._redis_json(location, journey, vehicle, info),
                        default=str,
                    )
                    pipeline.set(f"vehicle{location.id}", redis_json, ex=900)
                    pipeline.geoadd(
                        "vehicle_location_locations",
                        (location.latlong.x, location.latlong.y, location.id),
                    )
                    operator_id = (
                        vehicle.operator_id if vehicle else None
                    ) or journey.operator_id
                    if operator_id:
                        pipeline.sadd(
                            f"operator{operator_id}vehicles", location.id
                        )
                pipeline.execute()
            except ConnectionError as e:
                logger.exception(f"Redis error: {e}")

        channel_layer = get_channel_layer()
        if channel_layer is not None and self._pending_appendages:
            try:
                async_to_sync(channel_layer.send)(
                    VEHICLE_POSITIONS_CHANNEL,
                    {
                        "type": "move_vehicles",
                        "items": self._pending_appendages,
                    },
                )
            except ChannelFull as e:
                logger.error(e)

        self._pending_writes = []
        self._pending_appendages = []

    # -- main loop -----------------------------------------------------------

    def flush(self):
        data = _fetch("/api/locations")
        if not isinstance(data, dict):
            return

        trains = data.get("train_locations") or []

        # fetch train-information for rids we haven't seen, concurrently
        # and bounded - cold start has ~1500 to get through
        rids = {t.get("rid") for t in trains if t.get("rid")}
        missing = [
            rid for rid in rids if rid not in self.infos
        ][:INFO_FETCH_BATCH]
        if missing:
            with ThreadPoolExecutor(max_workers=INFO_FETCH_WORKERS) as pool:
                for rid, info in pool.map(
                    lambda r: (
                        r,
                        _fetch(f"/api/train-information/{r}"),
                    ),
                    missing,
                ):
                    if isinstance(info, dict) and info.get("rid"):
                        self.infos[rid] = info
            while len(self.infos) > INFO_CACHE_SIZE:
                del self.infos[next(iter(self.infos))]

        live_rids = set()
        written = 0

        for train in trains:
            rid = train.get("rid")
            if not rid:
                continue
            live_rids.add(rid)

            info = self.infos.get(rid)
            if info is None:
                continue
            journey = self.get_journey(rid, info)

            location = self.create_location(rid, journey, train)
            if location is None:
                continue

            vehicle = journey.vehicle
            location.id = vehicle.id if vehicle else -journey.id
            self.queue_redis_write(location, journey, vehicle, info)
            written += 1

        self.flush_redis()
        self._process_rtt()
        self._check_scrape_candidates(live_rids)

        # evict journeys for rids no longer reporting
        for rid in list(self.journeys):
            if rid not in live_rids and len(self.journeys) > 20000:
                del self.journeys[rid]
        for rid in list(self.infos):
            if rid not in live_rids and len(self.infos) > INFO_CACHE_SIZE * 2:
                del self.infos[rid]

        if written:
            logger.info("signalbox: wrote %s trains", written)

    def update(self):
        append_status("signalbox_status", {"status": "started"})
        logger.info("signalbox importer started")
        while True:
            try:
                self.flush()
            except Exception:
                logger.exception("signalbox flush error")
            time.sleep(self.wait)

    def handle(self, *args, **options):
        self.do_source()
        threading.Thread(target=self._scrape_worker, daemon=True).start()
        self.update()
