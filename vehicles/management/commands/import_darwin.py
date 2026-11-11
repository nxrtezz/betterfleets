"""National Rail (Darwin Push Port) live train importer.

Consumes the Darwin Push Port STOMP feed (headcodes, calling points,
expected times, formations) and mirrors it into the same Redis structures
as the other vehicle importers, so trains appear on the live map.

Darwin does not provide GPS positions - positions are interpolated between
calling points using expected times (see vehicles/darwin/position.py).

Journeys exist without a Vehicle until Darwin's formation data identifies
a train unit; the journey is then tracked under a negative Redis id
(vehicle{-journey.id}) like the FlixBus importer.
"""

import json
import logging
import os
import queue
from datetime import UTC, datetime, timedelta

from channels.exceptions import ChannelFull
from channels.layers import get_channel_layer
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand
from django.utils import timezone
from asgiref.sync import async_to_sync
from redis.exceptions import ConnectionError

from busstops.models import DataSource, Operator
from vehicles.darwin.client import start_listener
from vehicles.darwin.messages import parse_pport
from vehicles.darwin.operators import get_operator, get_toc_name
from vehicles.darwin.position import (
    get_delay,
    interpolate_position,
    point_datetime,
    service_window,
)
from vehicles.darwin.reference import get_reference_data
from vehicles.darwin.state import DarwinState
from vehicles.darwin.tiploc import TiplocResolver
from vehicles.models import (
    Vehicle,
    VehicleCode,
    VehicleJourney,
    VehicleLocation,
    VehicleType,
)
from vehicles.utils import VEHICLE_POSITIONS_CHANNEL, append_status, redis_client

logger = logging.getLogger(__name__)

FLUSH_INTERVAL = 15  # seconds between redis/db writes
STATE_RETENTION_DAYS = 2


def _vehicle_unit_number(coaches: list[dict]) -> str | None:
    """best-effort train unit identifier from formation coach data"""
    for coach in coaches:
        for attr in ("stockNumber", "unitNumber", "fleetNumber", "number"):
            if value := coach.get(attr):
                return str(value)
    return None


def _first_public_name(points: list[dict], resolver: TiplocResolver) -> str:
    for point in reversed(points):
        if point.get("type") in {"destination", "call"} and point.get("tpl"):
            return resolver.get_name(point["tpl"]) or point["tpl"]
    return ""


def _origin_time(state) -> datetime | None:
    for point in state.points:
        if point.get("type") == "origin":
            return point_datetime(
                state.service_date, point.get("ptd") or point.get("wtd")
            )
    return None


class Command(BaseCommand):
    source_name = "Darwin"
    wait = FLUSH_INTERVAL

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = None
        self.reference = None
        self.resolver = None
        self.state = DarwinState()
        self.message_queue = queue.Queue(maxsize=200_000)
        self.listener = None
        self.operators = {}
        self.journeys: dict[str, VehicleJourney] = {}
        self.signatures: dict[str, tuple] = {}
        self.operator_codes = {}
        self._pending_writes = []
        self._pending_appendages = []

    def do_source(self):
        self.source, _ = DataSource.objects.get_or_create(
            name=self.source_name,
            defaults={"url": "https://opendata.nationalrail.co.uk/"},
        )
        self.reference = get_reference_data()
        self.resolver = TiplocResolver(self.reference)
        return self

    # -- feed handling ----------------------------------------------------

    def _on_status(self, status, detail=None):
        append_status("darwin_status", {"status": status, "detail": detail})

    def _drain_queue(self):
        updates = 0
        while True:
            try:
                xml = self.message_queue.get_nowait()
            except queue.Empty:
                break
            ts = datetime.now(UTC).isoformat()
            for update in parse_pport(xml):
                update["_ts"] = ts
                self.state.apply(update)
                updates += 1
        return updates

    # -- vehicle / journey resolution -------------------------------------

    def get_vehicle(self, state) -> tuple[Vehicle | None, bool]:
        unit = _vehicle_unit_number(state.coaches)
        if not unit:
            return None, False

        operator = self.get_state_operator(state)
        code = f"{state.toc}:{unit}" if state.toc else unit

        # code already includes the TOC prefix, so it's unique per operator
        vehicle = Vehicle.objects.filter(
            source=self.source, code__iexact=code
        ).first()
        if vehicle:
            return vehicle, False

        vehicle = Vehicle(
            slug=f"darwin-{code.lower().replace(':', '-')}",
            code=code,
            name=unit,
            operator=operator,
            source=self.source,
        )
        vehicle_type, _ = VehicleType.objects.get_or_create(
            name="train", defaults={"style": "train"}
        )
        vehicle.vehicle_type = vehicle_type
        vehicle.save()
        VehicleCode.objects.get_or_create(
            vehicle=vehicle, scheme="Darwin", code=unit
        )
        return vehicle, True

    def get_state_operator(self, state) -> Operator | None:
        if state.toc in self.operator_codes:
            return self.operator_codes[state.toc]
        toc_name = get_toc_name(state.toc, self.reference)
        operator = get_operator(state.toc, toc_name, self.source, self.operators)
        self.operator_codes[state.toc] = operator
        return operator

    def get_journey(self, state) -> VehicleJourney:
        rid = state.rid
        if rid in self.journeys:
            return self.journeys[rid]

        journey = VehicleJourney.objects.filter(code=rid, source=self.source).first()
        if journey is None:
            ssd = state.service_date
            points = state.merged_points()
            destination = _first_public_name(points, self.resolver)
            journey_datetime = _origin_time(state) or timezone.now()

            journey = VehicleJourney(
                datetime=journey_datetime,
                date=ssd or timezone.localdate(),
                route_name=state.headcode or state.uid or "",
                code=rid,
                destination=destination,
                source=self.source,
                operator=self.get_state_operator(state),
            )
            journey.save()

        self.journeys[rid] = journey
        return journey

    # -- location / redis ---------------------------------------------------

    def create_location(self, state, journey, now) -> VehicleLocation | None:
        points = state.merged_points()
        ssd = state.service_date
        if ssd is None:
            return None

        position = interpolate_position(
            points, ssd, now, self.resolver.get_coord
        )
        if position is None:
            return None

        lon, lat = position["coord"]
        location = VehicleLocation(
            latlong=Point(lon, lat, srid=4326),
            heading=position.get("heading"),
            delay=get_delay(points, ssd, now),
            prev_stop=position.get("prev_tpl"),
            next_stop=position.get("next_tpl"),
        )
        location.datetime = now
        location.journey = journey

        return location

    def _redis_json(self, location, journey, vehicle, state) -> dict:
        redis_json = location.get_redis_json()

        if vehicle is None:
            toc_name = get_toc_name(state.toc, self.reference)
            redis_json["vehicle"] = {
                "name": f"{state.headcode or ''} {toc_name or state.toc or ''}".strip(),
                "features": "train",
            }
        if state.toc:
            redis_json.setdefault("service", {})["toc"] = state.toc

        return redis_json

    def handle_service(self, rid: str, state) -> bool:
        """-> True if handled (signature can be recorded),
        False if it should be retried next flush"""
        if not state.is_passenger or state.cancelled or state.deactivated:
            return True
        if not state.headcode and not state.toc:
            return True  # no schedule seen yet - can't identify the service

        now = timezone.now()
        ssd = state.service_date
        if ssd is None:
            return True

        vehicle, _ = self.get_vehicle(state)
        journey = self.get_journey(state)

        # don't put a marker on the map hours before departure or long
        # after arrival - return False so the service is retried next flush
        points = state.merged_points()
        if window := service_window(points, ssd):
            if now < window[0] - timedelta(minutes=30):
                return False
            if now > window[1] + timedelta(hours=1):
                return True  # finished - mark handled, let redis keys expire

        # attach/detach vehicle on the journey
        if vehicle and journey.vehicle_id != vehicle.id:
            old_negative_key = f"vehicle{-journey.id}"
            journey.vehicle = vehicle
            journey.save(update_fields=["vehicle"])
            if vehicle.latest_journey_id != journey.id:
                vehicle.latest_journey = journey
                vehicle.save(update_fields=["latest_journey"])
            # the journey was previously tracked under a negative id -
            # drop the stale redis entry so we don't show two markers
            if redis_client:
                try:
                    redis_client.delete(old_negative_key)
                except ConnectionError:
                    pass
        elif not vehicle and journey.vehicle_id:
            # unit no longer reported - keep the vehicle attached; the
            # journey keeps tracking under vehicle.id
            pass

        location = self.create_location(state, journey, now)
        if location is None:
            return True  # no resolvable position - don't retry every flush

        vehicle = journey.vehicle or vehicle
        location.id = vehicle.id if vehicle else -journey.id

        self.queue_redis_write(location, journey, vehicle, state)
        self._log_journey_data(journey, state)
        return True

    def _log_journey_data(self, journey, state):
        """store the raw feed state on the journey for debugging"""
        data = {
            "uid": state.uid,
            "toc": state.toc,
            "headcode": state.headcode,
            "train_cat": state.train_cat,
            "cancelled": state.cancelled,
            "cancel_reason": state.cancel_reason,
            "points": state.merged_points(),
            "coaches": state.coaches,
        }
        journey.data = data
        journey.save(update_fields=["data"])

    def queue_redis_write(self, location, journey, vehicle, state):
        """buffer a redis write; flushed in one pipeline per cycle"""
        self._pending_writes.append(
            (location, journey, vehicle, state)
        )
        self._pending_appendages.append(
            (
                journey.get_redis_key(),
                int(location.datetime.timestamp()),
                location.latlong.x,
                location.latlong.y,
            )
        )

    def flush_redis(self):
        if not self._pending_writes:
            return
        if redis_client:
            try:
                pipeline = redis_client.pipeline(transaction=False)
                for location, journey, vehicle, state in self._pending_writes:
                    redis_json = json.dumps(
                        self._redis_json(location, journey, vehicle, state),
                        default=str,
                    )
                    pipeline.set(
                        f"vehicle{location.id}", redis_json, ex=900
                    )
                    pipeline.geoadd(
                        "vehicle_location_locations",
                        (
                            location.latlong.x,
                            location.latlong.y,
                            location.id,
                        ),
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

    # -- main loop ---------------------------------------------------------

    def flush(self):
        """apply queued messages and write changed services to redis/db"""
        self._drain_queue()

        now_date = timezone.localdate()
        if not hasattr(self, "_last_prune") or (
            now_date - self._last_prune
        ).days >= 1:
            self.state.prune_before(now_date - timedelta(days=STATE_RETENTION_DAYS))
            self._last_prune = now_date

        changed = 0
        for rid, state in list(self.state.services.items()):
            signature = state.signature()
            if self.signatures.get(rid) == signature:
                continue
            try:
                if self.handle_service(rid, state):
                    self.signatures[rid] = signature
                    changed += 1
            except Exception:
                logger.exception("error handling darwin service %s", rid)

        self.flush_redis()

        if changed:
            logger.info("darwin: wrote %s changed services", changed)

        # evict signatures/journeys for pruned rids
        live = set(self.state.services)
        for rid in list(self.signatures):
            if rid not in live:
                del self.signatures[rid]
        for rid in list(self.journeys):
            if rid not in live and len(self.journeys) > 20000:
                del self.journeys[rid]

    def update(self):
        append_status("darwin_status", {"status": "started"})
        logger.info("darwin importer started")

        while True:
            try:
                self.flush()
            except Exception:
                logger.exception("darwin flush error")
            from time import sleep
            sleep(self.wait)

    def add_arguments(self, parser):
        parser.add_argument("--immediate", action="store_true")

    def handle(self, *args, **options):
        missing = [
            name
            for name in (
                "DARWIN_STOMP_HOST",
                "DARWIN_STOMP_USER",
                "DARWIN_STOMP_PASSWORD",
            )
            if not os.environ.get(name)
        ]
        if not (
            os.environ.get("DARWIN_STOMP_DESTINATION")
            or os.environ.get("DARWIN_STOMP_QUEUE")
        ):
            missing.append("DARWIN_STOMP_DESTINATION")
        if missing:
            self.stderr.write(
                self.style.ERROR(f"missing env vars: {', '.join(missing)}")
            )
            return

        self.do_source()

        if options.get("immediate"):
            # connect, collect for a short window, flush once, exit
            self.listener = start_listener(self.message_queue, self._on_status)
            from time import sleep
            sleep(30)
            self.listener.stop()
            self.flush()
            self.flush()
            logger.info("darwin: immediate run complete")
        else:
            self.listener = start_listener(self.message_queue, self._on_status)
            try:
                self.update()
            finally:
                self.listener.stop()
