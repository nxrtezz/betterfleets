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

import json
import logging
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
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
from vehicles.utils import VEHICLE_POSITIONS_CHANNEL, append_status, redis_client

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get(
    "SIGNALBOX_API_BASE", "https://map-api.production.signalbox.io"
)
POLL_INTERVAL = 30  # seconds between /api/locations polls
INFO_CACHE_SIZE = 6000
INFO_FETCH_BATCH = 100  # max train-information lookups per poll
INFO_FETCH_WORKERS = 8
RTT_LOOKUP_INTERVAL = 40  # ~90/hour, under the 100/hour plan limit
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
        self.rtt_queue: list[tuple[str, VehicleJourney]] = []
        self.rtt_queued: set[str] = set()
        self.rtt_retries: dict[str, int] = {}
        self._rtt_next = 0.0
        self._pending_writes = []
        self._pending_appendages = []

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
        self.rtt_queue.append((uid, journey))

    def _process_rtt(self):
        if not self.rtt_queue or time.time() < self._rtt_next:
            return
        self._rtt_next = time.time() + RTT_LOOKUP_INTERVAL
        uid, journey = self.rtt_queue.pop(0)
        try:
            service = self.rtt.service(uid, journey.date.isoformat())
        except RttError as e:
            logger.warning("rtt lookup failed for %s: %s", uid, e)
            # retry once - transient failures shouldn't lose the unit
            if self.rtt_retries.get(uid, 0) < 1:
                self.rtt_retries[uid] = self.rtt_retries.get(uid, 0) + 1
                self.rtt_queue.append((uid, journey))
            return
        self._apply_rtt(journey, service)

    def _apply_rtt(self, journey: VehicleJourney, service: dict):
        summary = allocation_summary(service)
        if summary is None:
            return
        tops = summary["tops"]
        leading_class = summary["leading_class"]

        journey.data = journey.data or {}
        journey.data["rtt"] = summary
        update_fields = ["data"]

        if tops and not journey.vehicle_id:
            vehicle = self.get_rtt_vehicle(tops, leading_class, journey)
            if vehicle:
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
        vehicle = Vehicle.objects.filter(
            source=self.rtt_source, code=tops
        ).first()
        if vehicle:
            if not vehicle.operator_id and journey.operator_id:
                vehicle.operator = journey.operator
                vehicle.save(update_fields=["operator"])
            return vehicle

        vehicle = Vehicle(
            slug=f"rtt-{tops}",
            code=tops,
            name=tops_display_name(tops, leading_class),
            operator=journey.operator,
            source=self.rtt_source,
        )
        vehicle_type, _ = VehicleType.objects.get_or_create(
            name="train", defaults={"style": "train"}
        )
        vehicle.vehicle_type = vehicle_type
        vehicle.save()
        VehicleCode.objects.get_or_create(
            vehicle=vehicle, scheme="TOPS", code=tops
        )
        return vehicle

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

        location = VehicleLocation(
            latlong=Point(lon, lat, srid=4326),
            delay=timedelta(minutes=train.get("delay") or 0),
            prev_stop=prev_stop,
            next_stop=next_stop,
        )
        location.datetime = now
        location.journey = journey
        return location

    def _redis_json(self, location, journey, vehicle, info) -> dict:
        redis_json = location.get_redis_json()

        if vehicle is None:
            name = " ".join(
                part
                for part in (
                    info.get("headcode"),
                    info.get("train_operator"),
                )
                if part
            )
            redis_json["vehicle"] = {
                "name": name or journey.route_name or "Train",
                "features": "train",
            }
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
        from channels.exceptions import ChannelFull
        from channels.layers import get_channel_layer
        from django.utils.asyncio import async_to_sync

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
        self.update()
