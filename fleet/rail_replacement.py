"""RTT replacement-bus normalization and BetterFleets timetable persistence."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.db import transaction

from busstops.models import DataSource, Operator, Service, StopPoint, StopUsage
from bustimes.models import Calendar, Route, StopTime, Trip

from .realtimetrains import RTTClient, RTTError


def _first(value, *keys):
    if not isinstance(value, dict):
        return None
    for key in keys:
        if value.get(key) is not None:
            return value[key]
    return None


def _code(value):
    code = _first(value, "shortCode", "short_code", "longCode", "long_code", "code")
    if code:
        return code[0] if isinstance(code, list) else code
    codes = _first(value, "shortCodes", "short_codes", "longCodes", "long_codes")
    if isinstance(codes, list) and codes:
        return codes[0]
    return None


def _location_code(location):
    return _code(_first(location, "location", "locationMetadata") or location)


def _location_name(location):
    return _first(
        _first(location, "location", "locationMetadata") or location,
        "description",
        "name",
    )


def _time_value(location, activity):
    temporal = _first(location, "temporalData", "temporal_data") or {}
    activity_data = temporal.get(activity) or {}
    return _first(
        activity_data,
        "scheduleAdvertised",
        "scheduleInternal",
        "realtimeForecast",
    )


def _parse_time(value, service_date):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    local = parsed.replace(tzinfo=None)
    midnight = datetime.combine(service_date, datetime.min.time())
    return timedelta(seconds=(local - midnight).total_seconds())


def _metadata(service):
    return service.get("scheduleMetadata") or {}


def _is_replacement(service):
    return (_metadata(service).get("modeType") or "").upper() in {
        "REPLACEMENT_BUS",
        "BUS",
        "SCHEDULED_BUS",
    }


def _identity(service):
    metadata = _metadata(service)
    return _first(metadata, "uniqueIdentity") or ":".join(
        str(part) for part in (
            metadata.get("namespace", "gb-nr"),
            metadata.get("identity"),
            metadata.get("departureDate"),
        ) if part
    )


def _operator(service):
    return _metadata(service).get("operator") or {}


def _service_locations(service):
    return service.get("locations") or []


def _normalize(service, service_date):
    locations = []
    for index, location in enumerate(_service_locations(service)):
        code = _location_code(location)
        if not code:
            continue
        arrival = _parse_time(_time_value(location, "arrival"), service_date)
        departure = _parse_time(_time_value(location, "departure"), service_date)
        locations.append(
            {
                "code": code.split(":", 1)[-1].upper(),
                "name": _location_name(location) or code,
                "arrival": arrival,
                "departure": departure,
                "sequence": index,
                "pick_up": (_first(location, "temporalData") or {}).get("scheduledCallType")
                not in {"ADVERTISED_SET_DOWN"},
                "set_down": True,
            }
        )
    return locations


def _local_stop(code, name):
    stop = (
        StopPoint.objects.filter(crs_code__iexact=code)
        .order_by("stop_type", "atco_code")
        .first()
    )
    if stop:
        return stop
    return (
        StopPoint.objects.filter(common_name__iexact=name)
        .order_by("stop_type", "atco_code")
        .first()
    )


def discover_replacements(
    dates: list[date],
    origin_code: str,
    destination_code: str,
    operator_code: str = "",
    client: RTTClient | None = None,
):
    client = client or RTTClient()
    found = []
    seen = set()
    for service_date in dates:
        for from_code, to_code, inbound in (
            (origin_code, destination_code, False),
            (destination_code, origin_code, True),
        ):
            candidates = client.location_services(from_code, service_date)
            for listing in candidates:
                metadata = _metadata(listing)
                identity = _identity(listing)
                seen_key = (identity, inbound)
                if not identity or seen_key in seen or not _is_replacement(listing):
                    continue
                operator = _operator(listing)
                if operator_code and operator.get("code", "").upper() != operator_code.upper():
                    continue
                detail = client.service(identity)
                locations = _normalize(detail, service_date)
                codes = [item["code"] for item in locations]
                if from_code.upper() not in codes or to_code.upper() not in codes:
                    continue
                origin_index = codes.index(from_code.upper())
                destination_index = codes.index(to_code.upper())
                if origin_index >= destination_index:
                    continue
                locations = locations[origin_index : destination_index + 1]
                found.append(
                    {
                        "date": service_date,
                        "identity": identity,
                        "headcode": metadata.get("trainReportingIdentity")
                        or metadata.get("identity")
                        or "RR",
                        "operator": operator,
                        "locations": locations,
                        "origin_index": origin_index,
                        "destination_index": destination_index,
                        "inbound": inbound,
                    }
                )
                seen.add(seen_key)
    return found


def _pattern_key(item):
    pattern = tuple(location["code"] for location in item["locations"])
    reverse = tuple(reversed(pattern))
    return min(pattern, reverse)


def group_replacements(items):
    groups = defaultdict(list)
    for item in items:
        groups[_pattern_key(item)].append(item)
    return [
        {"pattern": list(pattern), "services": services}
        for pattern, services in sorted(groups.items())
    ]


@transaction.atomic
def publish_replacements(items, source_name="Realtime Trains rail replacements"):
    if not items:
        raise RTTError("RTT returned no matching replacement-bus services.")
    source, _ = DataSource.objects.get_or_create(
        name=source_name,
        defaults={"url": "https://data.rtt.io"},
    )
    operator_data = items[0]["operator"]
    operator_code = operator_data.get("code") or "RTT"
    operator, _ = Operator.objects.get_or_create(
        noc=operator_code,
        defaults={
            "name": operator_data.get("name") or operator_code,
            "vehicle_mode": "bus",
        },
    )
    groups = group_replacements(items)
    created_trips = []
    for group in groups:
        all_services = group["services"]
        outbound_services = [
            item for item in all_services if not item["inbound"]
        ]
        inbound_services = [item for item in all_services if item["inbound"]]
        representative = (outbound_services or inbound_services)[0]
        pattern = [
            location["code"] for location in representative["locations"]
        ]
        names = {
            location["code"]: location["name"]
            for item in all_services
            for location in item["locations"]
        }
        stops = [_local_stop(code, names.get(code, code)) for code in pattern]
        if any(stop is None for stop in stops):
            missing = [code for code, stop in zip(pattern, stops) if stop is None]
            raise RTTError(
                "No BetterFleets station exists for RTT stop code(s): "
                + ", ".join(missing)
            )
        headcodes = sorted({item["headcode"] for item in all_services})
        line_name = headcodes[0] if len(headcodes) == 1 else "RR"
        service_code = "rtt-rr-" + hashlib.sha1(
            "|".join(sorted(pattern)).encode()
        ).hexdigest()[:12]
        service, _ = Service.objects.get_or_create(
            source=source,
            service_code=service_code,
            defaults={
                "line_name": line_name,
                "description": f"{stops[0].common_name} – {stops[-1].common_name}",
                "mode": "bus",
                "is_rail_replacement": True,
                "train_operator": operator.name,
                "tracking": True,
            },
        )
        service.operator.add(operator)
        for inbound, direction_items in (
            (False, outbound_services),
            (True, inbound_services),
        ):
            if not direction_items:
                continue
            direction_pattern = [
                location["code"] for location in direction_items[0]["locations"]
            ]
            direction_stops = [
                _local_stop(code, names.get(code, code))
                for code in direction_pattern
            ]
            route, _ = Route.objects.get_or_create(
                source=source,
                code=f"{service_code}:{','.join(direction_pattern)}",
                defaults={
                    "service": service,
                    "service_code": service_code,
                    "line_name": line_name,
                    "description": service.description,
                    "origin": direction_stops[0].common_name,
                    "destination": direction_stops[-1].common_name,
                    "start_date": min(item["date"] for item in direction_items),
                    "end_date": max(item["date"] for item in direction_items),
                },
            )
            for index, stop in enumerate(direction_stops):
                StopUsage.objects.update_or_create(
                    service=service,
                    stop=stop,
                    inbound=inbound,
                    defaults={"order": index, "line_name": line_name},
                )
            for item in direction_items:
                calendar, _ = Calendar.objects.get_or_create(
                    source=source,
                    start_date=item["date"],
                    end_date=item["date"],
                    summary=f"RTT {item['identity']}",
                    defaults={
                        ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[
                            item["date"].weekday()
                        ]: True,
                    },
                )
                trip, created = Trip.objects.get_or_create(
                    route=route,
                    vehicle_journey_code=item["identity"],
                    defaults={
                        "calendar": calendar,
                        "operator": operator,
                        "headsign": item["headcode"],
                        "inbound": inbound,
                        "start": item["locations"][0]["departure"]
                        or item["locations"][0]["arrival"],
                        "end": item["locations"][-1]["arrival"]
                        or item["locations"][-1]["departure"],
                    },
                )
                if created:
                    StopTime.objects.bulk_create(
                        [
                            StopTime(
                                trip=trip,
                                stop=stop,
                                sequence=index,
                                arrival=location["arrival"],
                                departure=location["departure"],
                                pick_up=location["pick_up"],
                                set_down=location["set_down"],
                            )
                            for index, (stop, location) in enumerate(
                                zip(direction_stops, item["locations"])
                            )
                        ]
                    )
                created_trips.append(trip)
    return created_trips
