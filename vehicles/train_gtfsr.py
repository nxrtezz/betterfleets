"""
GTFS-Realtime vehicle positions for the train map.

**United Kingdom:** There is no single anonymous public URL for all GB National Rail
positions (unlike Ireland’s NTA). You typically obtain one or more GTFS-RT VehiclePosition
protobuf feeds from the `Rail Data Marketplace <https://www.raildata.org.uk>`_
(or your data provider), set ``GTFSR_TRAIN_VEHICLE_POSITIONS_URL`` or
``GTFSR_TRAIN_VEHICLE_POSITIONS_URLS``, and use ``GTFSR_TRAIN_ROUTE_FILTER_MODE=none``
when the feed is already train-only. Use ``GTFSR_TRAIN_BEARER_TOKEN`` or configure
``BODS_API_KEY`` when the feed is hosted on DfT BODS-style endpoints.

**Ireland:** Default single URL remains the NTA Vehicles feed + optional trip delays.
"""

from __future__ import annotations

import logging
import time
import zlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache
from google.transit import gtfs_realtime_pb2

logger = logging.getLogger(__name__)

CACHE_KEY_NORMALIZED = "train_gtfsr:normalized_v2"
CACHE_TTL_SECONDS = 12
REQUEST_TIMEOUT = 12
MAX_RETRIES = 3


def stable_train_numeric_id(vehicle_uid: str) -> int:
    """Stable positive int for MapLibre / DOM data attributes."""
    return zlib.crc32(vehicle_uid.encode("utf-8")) & 0x7FFFFFFF


def route_matches_train_heuristic(route_id: str) -> bool:
    if not route_id:
        return False
    rid = route_id.lower()
    for part in settings.GTFSR_TRAIN_ROUTE_SUBSTRINGS:
        if part and part.lower() in rid:
            return True
    return False


def _train_feed_urls() -> list[str]:
    if settings.GTFSR_TRAIN_VEHICLE_POSITIONS_URLS:
        return list(settings.GTFSR_TRAIN_VEHICLE_POSITIONS_URLS)
    u = (settings.GTFSR_TRAIN_VEHICLE_POSITIONS_URL or "").strip()
    return [u] if u else []


def _request_kwargs_for_url(url: str) -> dict[str, Any]:
    headers = {"User-Agent": settings.GTFSR_TRAIN_USER_AGENT}
    params: dict[str, str] = {}

    if settings.NTA_API_KEY and "nationaltransport.ie" in url:
        headers["x-api-key"] = settings.NTA_API_KEY

    host = urlparse(url).netloc.lower()
    if settings.BODS_API_KEY and (
        "bus-data.dft.gov.uk" in host or host.endswith(".bus-data.dft.gov.uk")
    ):
        from vehicles.realtime.bods_auth import get_bods_request_kwargs

        bods = get_bods_request_kwargs()
        headers.update(bods.get("headers", {}))
        params.update(bods.get("params", {}))

    if settings.GTFSR_TRAIN_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GTFSR_TRAIN_BEARER_TOKEN}"

    return {"headers": headers, "params": params}


def _fetch_one_url(url: str) -> bytes | None:
    if not url:
        return None
    session = requests.Session()
    req_kw = _request_kwargs_for_url(url)
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT, **req_kw)
            if response.ok:
                return response.content
            last_error = RuntimeError(f"HTTP {response.status_code}")
        except (requests.RequestException, OSError) as e:
            last_error = e
        time.sleep(0.35 * (2**attempt))

    logger.warning("train_gtfsr: fetch failed for %s after retries: %s", url, last_error)
    return None


def _trip_delay_seconds_by_trip_id() -> dict[str, int]:
    if not settings.GTFSR_TRAIN_USE_TRIP_UPDATES:
        return {}
    feed_name = (settings.GTFSR_TRAIN_TRIP_UPDATES_FEED or "").strip()
    if not feed_name:
        return {}
    try:
        from departures.gtfsr import get_trip_updates
    except ImportError:
        return {}

    updates = get_trip_updates(feed_name)
    if not updates:
        return {}

    delays: dict[str, int] = {}
    for trip_id, trip_update in updates.items():
        delay = trip_update.get("delay")
        if isinstance(delay, (int, float)):
            delays[trip_id] = int(delay)
            continue
        st_updates = trip_update.get("stopTimeUpdate") or []
        for su in st_updates:
            if "delay" in su and isinstance(su["delay"], (int, float)):
                delays[trip_id] = int(su["delay"])
                break
    return delays


def _include_route(route_id: str) -> bool:
    if settings.GTFSR_TRAIN_ROUTE_ALLOWLIST:
        return route_id in settings.GTFSR_TRAIN_ROUTE_ALLOWLIST
    if settings.GTFSR_TRAIN_ROUTE_FILTER_MODE == "none":
        return True
    return route_matches_train_heuristic(route_id)


def _normalize_feed(
    raw: bytes,
    *,
    trip_delays: dict[str, int],
    uid_prefix: str,
    now: datetime,
) -> list[dict[str, Any]]:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw)
    out: list[dict[str, Any]] = []

    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        vp = entity.vehicle
        if not vp.HasField("position"):
            continue

        pos = vp.position
        lat = float(pos.latitude)
        lon = float(pos.longitude)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        route_id = ""
        trip_id = ""
        headsign = ""
        start_time = ""
        if vp.HasField("trip"):
            trip = vp.trip
            route_id = trip.route_id or ""
            trip_id = trip.trip_id or ""
            headsign = trip.trip_headsign or ""
            start_time = trip.start_time or ""

        if not _include_route(route_id):
            continue

        vehicle_label = ""
        base_uid = ""
        if vp.HasField("vehicle"):
            vid = vp.vehicle
            base_uid = vid.id or vid.label or trip_id or f"{route_id}:{lon:.5f}:{lat:.5f}"
            vehicle_label = vid.label or vid.id or "Train"
        else:
            base_uid = trip_id or f"{route_id}:{lon:.5f}:{lat:.5f}"
            vehicle_label = "Train"

        vehicle_uid = f"{uid_prefix}{base_uid}"

        bearing = None
        if pos.HasField("bearing"):
            bearing = float(pos.bearing)

        timestamp = now
        if vp.HasField("timestamp"):
            timestamp = datetime.fromtimestamp(vp.timestamp, tz=timezone.utc)

        delay = None
        if trip_id and trip_id in trip_delays:
            delay = trip_delays[trip_id]

        colour = "#2d6a9f"
        line_name = route_id or "Train"
        if headsign:
            line_name = f"{line_name} → {headsign}" if route_id else headsign

        numeric_id = stable_train_numeric_id(vehicle_uid)

        out.append(
            {
                "id": numeric_id,
                "coordinates": [lon, lat],
                "heading": bearing,
                "datetime": timestamp.isoformat().replace("+00:00", "Z"),
                "destination": headsign or "",
                "delay": delay,
                "trip_id": None,
                "journey_id": None,
                "route_id": route_id,
                "trip_descriptor_id": trip_id,
                "start_time": start_time,
                "service": {
                    "line_name": route_id or "Train",
                    "url": "",
                },
                "vehicle": {
                    "url": "",
                    "name": vehicle_label,
                    "livery": None,
                    "colour": colour,
                    "text_colour": "#ffffff",
                    "css": colour,
                    "right_css": colour,
                },
            }
        )

    return out


def _parse_and_normalize() -> list[dict[str, Any]]:
    urls = _train_feed_urls()
    if not urls:
        return []

    trip_delays = _trip_delay_seconds_by_trip_id()
    now = datetime.now(timezone.utc)
    multi = len(urls) > 1
    combined: list[dict[str, Any]] = []

    for i, url in enumerate(urls):
        raw = _fetch_one_url(url)
        if not raw:
            continue
        prefix = f"{i}:" if multi else ""
        combined.extend(
            _normalize_feed(raw, trip_delays=trip_delays, uid_prefix=prefix, now=now)
        )

    return combined


def get_normalized_train_positions(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    if not force_refresh:
        cached = cache.get(CACHE_KEY_NORMALIZED)
        if cached is not None:
            return cached

    items = _parse_and_normalize()
    cache.set(CACHE_KEY_NORMALIZED, items, CACHE_TTL_SECONDS)
    return items


def filter_by_bounding_box(
    items: list[dict[str, Any]],
    *,
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float,
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if xmin <= item["coordinates"][0] <= xmax
        and ymin <= item["coordinates"][1] <= ymax
    ]
