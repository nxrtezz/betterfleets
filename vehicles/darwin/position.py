"""Train position interpolation between calling points.

Darwin gives times at TIPLOCs, not positions. We interpolate linearly
between consecutive calling points using expected times (falling back to
public/working times), the same approach used by National Rail enquiry
trackers.
"""

import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def parse_hhmm(value: str | None) -> timedelta | None:
    """'HH:MM[:SS]' (can exceed 24:00) -> timedelta since service-day midnight"""
    if not value:
        return None
    parts = value.split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    return timedelta(hours=h, minutes=m, seconds=s)


def point_datetime(ssd: date, hhmmss: str | None) -> datetime | None:
    """combine a service date and 'HH:MM[:SS]' into an aware Europe/London datetime"""
    delta = parse_hhmm(hhmmss)
    if delta is None:
        return None
    naive = datetime.combine(ssd, time.min) + delta
    return naive.replace(tzinfo=LONDON)


def _first(*values):
    for value in values:
        if value is not None:
            return value
    return None


def effective_times(point: dict, ssd: date) -> dict:
    """best-known times for a merged calling point, as datetimes.

    Priority: reported actual (at), Darwin estimate (et), working estimate
    (wet), public timetable, working timetable.
    """
    out = {}
    for kind in ("arr", "dep"):
        candidates = [
            point_datetime(ssd, point.get(f"{kind}_{suffix}"))
            for suffix in ("at", "et", "wet")
            if point.get(f"{kind}_{suffix}")
        ]
        pub_key = "pta" if kind == "arr" else "ptd"
        work_key = "wta" if kind == "arr" else "wtd"
        candidates += [
            point_datetime(ssd, point.get(pub_key)),
            point_datetime(ssd, point.get(work_key)),
        ]
        out[kind] = next((t for t in candidates if t is not None), None)
    out["pass"] = _first(
        point_datetime(ssd, point["pass_at"]) if point.get("pass_at") else None,
        point_datetime(ssd, point["pass_et"]) if point.get("pass_et") else None,
        point_datetime(ssd, point["pass_wet"]) if point.get("pass_wet") else None,
        point_datetime(ssd, point.get("wtp")),
    )
    return out


def point_position_time(point: dict, times: dict) -> datetime | None:
    """the time used for ordering/interpolation at this point:
    departure if it stops, else pass/arrival"""
    return times.get("dep") or times.get("pass") or times.get("arr")


def interpolate_position(points: list[dict], ssd: date, now: datetime,
                         get_coord) -> dict | None:
    """compute {latlong:(lon,lat), heading, prev_tpl, next_tpl, fraction}

    get_coord(tpl) -> (lon, lat) or None
    """
    timed = []
    for point in points:
        if point.get("cancelled") or not point.get("tpl"):
            continue
        times = effective_times(point, ssd)
        when = point_position_time(point, times)
        if when is None:
            continue
        coord = get_coord(point["tpl"])
        timed.append({"tpl": point["tpl"], "type": point.get("type"),
                      "when": when, "times": times, "coord": coord,
                      "point": point})

    if not timed:
        return None

    # clamp to first/last known position
    if now <= timed[0]["when"]:
        if timed[0]["coord"]:
            return {"coord": timed[0]["coord"], "fraction": 0.0,
                    "prev_tpl": None, "next_tpl": timed[0]["tpl"],
                    "segment": timed[0]}
        # origin has no coord - try the next point that does
        for entry in timed[1:]:
            if entry["coord"]:
                return {"coord": entry["coord"], "fraction": 0.0,
                        "prev_tpl": None, "next_tpl": entry["tpl"],
                        "segment": entry}
        return None

    if now >= timed[-1]["when"]:
        if timed[-1]["coord"]:
            return {"coord": timed[-1]["coord"], "fraction": 1.0,
                    "prev_tpl": timed[-1]["tpl"], "next_tpl": None,
                    "segment": timed[-1]}
        for entry in reversed(timed[:-1]):
            if entry["coord"]:
                return {"coord": entry["coord"], "fraction": 1.0,
                        "prev_tpl": entry["tpl"], "next_tpl": None,
                        "segment": entry}
        return None

    # find surrounding timed points with coords
    prev_i = next_i = None
    for i, entry in enumerate(timed):
        if entry["when"] <= now:
            prev_i = i
        elif next_i is None:
            next_i = i
            break
    if prev_i is None or next_i is None:
        return None

    # walk back/forward to entries that have coords
    prev = next((timed[j] for j in range(prev_i, -1, -1) if timed[j]["coord"]), None)
    nxt = next((timed[j] for j in range(next_i, len(timed)) if timed[j]["coord"]), None)
    if prev is None and nxt is None:
        return None

    if prev is None:
        return {"coord": nxt["coord"], "fraction": 0.0,
                "prev_tpl": None, "next_tpl": nxt["tpl"], "segment": nxt}
    if nxt is None:
        return {"coord": prev["coord"], "fraction": 1.0,
                "prev_tpl": prev["tpl"], "next_tpl": None, "segment": prev}

    span = (nxt["when"] - prev["when"]).total_seconds()
    fraction = 0.0 if span <= 0 else max(
        0.0, min(1.0, (now - prev["when"]).total_seconds() / span)
    )

    coord = _lerp(prev["coord"], nxt["coord"], fraction)
    heading = None
    if prev["coord"] != nxt["coord"]:
        heading = _bearing(prev["coord"], nxt["coord"])

    return {"coord": coord, "fraction": fraction,
            "prev_tpl": prev["tpl"], "next_tpl": nxt["tpl"],
            "prev": prev, "next": nxt, "heading": heading,
            "segment": prev}


def _lerp(a: tuple[float, float], b: tuple[float, float], f: float) -> tuple[float, float]:
    """linear interpolation of (lon, lat); fine at railway segment scales"""
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> int:
    """bearing in degrees from (lon, lat) a to (lon, lat) b"""
    a_lon, a_lat = math.radians(a[0]), math.radians(a[1])
    b_lon, b_lat = math.radians(b[0]), math.radians(b[1])
    y = math.sin(b_lon - a_lon) * math.cos(b_lat)
    x = math.cos(a_lat) * math.sin(b_lat) - math.sin(a_lat) * math.cos(
        b_lat
    ) * math.cos(b_lon - a_lon)
    return round(math.degrees(math.atan2(y, x))) % 360


def service_window(points: list[dict], ssd: date) -> tuple[datetime, datetime] | None:
    """(first, last) expected datetimes for the service, for deciding
    whether it's reasonable to show it on the live map"""
    times = []
    for point in points:
        times_dict = effective_times(point, ssd)
        when = (
            times_dict["dep"]
            or times_dict["pass"]
            or times_dict["arr"]
        )
        if when is not None:
            times.append(when)
    if not times:
        return None
    return min(times), max(times)


def get_delay(points: list[dict], ssd: date, now: datetime) -> timedelta | None:
    """delay vs the public timetable at the current interpolated position.

    Uses only public calling points (those with pta/ptd), interpolating the
    public time at the same fraction as the expected-time position.
    """
    public = []
    for point in points:
        if point.get("cancelled") or not point.get("tpl"):
            continue
        if not (point.get("pta") or point.get("ptd")):
            continue
        times = effective_times(point, ssd)
        when = point_position_time(point, times)
        # public equivalent of `when`: ptd for departure-ish, pta for arrival
        pub = None
        if times.get("dep") and point.get("ptd"):
            pub = point_datetime(ssd, point["ptd"])
        elif times.get("arr") and point.get("pta"):
            pub = point_datetime(ssd, point["pta"])
        elif times.get("pass") and point.get("wtp"):
            pub = point_datetime(ssd, point["wtp"])
        if when is None or pub is None:
            continue
        public.append({"when": when, "pub": pub, "tpl": point["tpl"]})

    if len(public) < 2:
        return None

    # find surrounding public points and interpolate the public time
    prev = nxt = None
    for entry in public:
        if entry["when"] <= now:
            prev = entry
        elif nxt is None:
            nxt = entry
            break
    if prev is None:
        prev = public[0]
    if nxt is None:
        nxt = public[-1]
    if prev is nxt:
        return now - prev["pub"]

    span = (nxt["when"] - prev["when"]).total_seconds()
    fraction = 0.0 if span <= 0 else max(
        0.0, min(1.0, (now - prev["when"]).total_seconds() / span)
    )
    pub_now = prev["pub"] + (nxt["pub"] - prev["pub"]) * fraction
    return now - pub_now
