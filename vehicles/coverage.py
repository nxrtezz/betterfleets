"""Compare genuinely live tracking with imported timetable and trip coverage."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from django.db.models import Count
from django.utils import timezone

from busstops.models import Operator, Service
from bustimes.models import Trip
from vehicles.models import Vehicle, VehicleJourney
from vehicles.utils import redis_client


def live_vehicle_payloads(client=None, now=None):
    client = client if client is not None else redis_client
    now = now or timezone.now()
    keys = [key for key in client.scan_iter(match="vehicle[0-9]*", count=2000)
            if (key.decode() if isinstance(key, bytes) else key)[7:].isdigit()]
    import json
    live = {}
    for offset in range(0, len(keys), 1000):
        batch = keys[offset:offset + 1000]
        for key, raw in zip(batch, client.mget(batch)):
            if not raw:
                continue
            try:
                data = json.loads(raw)
                observed = datetime.fromisoformat(data["datetime"])
                age = now - observed
                if not -timedelta(minutes=2) <= age <= timedelta(minutes=15):
                    continue
                vehicle_id = int((key.decode() if isinstance(key, bytes) else key)[7:])
                live[vehicle_id] = data
            except (KeyError, TypeError, ValueError):
                continue
    return live


def operator_coverage(live):
    vehicles = list(Vehicle.objects.filter(pk__in=live).values("id", "operator_id"))
    nocs = {v["operator_id"] for v in vehicles if v["operator_id"]}
    tracking = Counter(v["operator_id"] for v in vehicles)
    ids = {int(data["journey_id"]) for data in live.values() if data.get("journey_id")}
    journeys = {j["id"]: j for j in VehicleJourney.objects.filter(pk__in=ids).values(
        "id", "service_id", "trip_id", "source__name",
    )}
    matched, with_service = Counter(), Counter()
    sources = defaultdict(Counter)
    for vehicle in vehicles:
        noc = vehicle["operator_id"]
        pk = live[vehicle["id"]].get("journey_id")
        journey = journeys.get(int(pk), {}) if pk else {}
        matched[noc] += bool(journey.get("trip_id"))
        with_service[noc] += bool(journey.get("service_id"))
        sources[noc][journey.get("source__name", "unknown")] += 1
    services = {row["operator"]: row["n"] for row in Service.objects.filter(
        operator__in=nocs, current=True,
    ).order_by().values("operator").annotate(n=Count("id", distinct=True))}
    trips = {row["route__service__operator"]: row["n"] for row in Trip.objects.filter(
        route__service__operator__in=nocs, route__service__current=True,
    ).order_by().values("route__service__operator").annotate(n=Count("id"))}
    rows = []
    for operator in Operator.objects.filter(noc__in=nocs):
        rail = set(sources[operator.pk]) <= {"Signalbox", "Darwin"}
        rows.append({
            "noc": operator.pk, "name": operator.name, "mode": operator.vehicle_mode,
            "tracking": tracking[operator.pk], "services": services.get(operator.pk, 0),
            "trips": trips.get(operator.pk, 0), "live_with_service": with_service[operator.pk],
            "live_with_trip": matched[operator.pk], "sources": dict(sources[operator.pk]),
            "timetable_expected": not rail,
        })
    return sorted(rows, key=lambda row: (-row["tracking"], row["noc"]))


def missing_timetables(rows, minimum=10):
    return [row for row in rows if row["timetable_expected"] and row["tracking"] >= minimum
            and (row["services"] == 0 or row["trips"] == 0) and row["live_with_trip"] == 0]


def coverage_alert(rows, minimum=10):
    missing = missing_timetables(rows, minimum)
    if not missing:
        return None
    examples = ", ".join(f'{row["noc"]} ({row["tracking"]} live)' for row in missing[:8])
    return f"{len(missing)} tracking operators lack timetable services/trips: {examples}"
