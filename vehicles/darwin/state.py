"""In-memory state for active Darwin services, merged from schedule,
TS (train status) and formation messages.
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)


class ServiceState:
    """one Darwin service (rid) - schedule calling points + live TS updates"""

    def __init__(self):
        self.rid = None
        self.uid = None
        self.headcode = None
        self.toc = None
        self.train_cat = None
        self.ssd = None  # service date "YYYY-MM-DD"
        self.is_passenger = True
        self.cancelled = False
        self.cancel_reason = None
        # ordered calling points from the schedule message
        self.points = []  # [{tpl,type,wta,wtd,wtp,pta,ptd,act,cancelled}]
        # TS updates, kept as an ordered list of {tpl, arr_et, dep_et, ...}
        self.ts_locations = []
        self.coaches = []
        self.late_reason = None
        self.deactivated = False
        self.first_seen = None
        self.last_seen = None

    @property
    def service_date(self) -> date | None:
        if not self.ssd:
            return None
        try:
            return date.fromisoformat(self.ssd)
        except ValueError:
            return None

    def apply_schedule(self, schedule: dict):
        self.rid = schedule["rid"]
        self.uid = schedule.get("uid") or self.uid
        self.headcode = schedule.get("headcode") or self.headcode
        self.toc = schedule.get("toc") or self.toc
        self.train_cat = schedule.get("train_cat") or self.train_cat
        self.ssd = schedule.get("ssd") or self.ssd
        self.is_passenger = schedule.get("is_passenger", True)
        self.cancelled = schedule.get("cancelled", False)
        self.cancel_reason = schedule.get("cancel_reason")
        if schedule.get("points"):
            self.points = schedule["points"]

    def apply_ts(self, ts: dict):
        self.rid = ts["rid"]
        self.uid = ts.get("uid") or self.uid
        self.ssd = ts.get("ssd") or self.ssd
        if ts.get("late_reason"):
            self.late_reason = ts["late_reason"]
        if ts.get("locations"):
            # replace the TS suffix wholesale - each TS message carries the
            # forecast for the remainder of the journey
            self.ts_locations = ts["locations"]

    def apply_formation(self, formation: dict):
        self.coaches = formation.get("coaches") or self.coaches

    @staticmethod
    def _minutes(value: str | None) -> float | None:
        if not value:
            return None
        try:
            h, m, s = (int(p) for p in value.split(":"))
        except ValueError:
            try:
                h, m = (int(p) for p in value.split(":"))
                s = 0
            except ValueError:
                return None
        return h * 60 + m + s / 60

    @staticmethod
    def _point_time(point: dict) -> float | None:
        for key in ("wtp", "wtd", "wta", "ptd", "pta"):
            if (minutes := ServiceState._minutes(point.get(key))) is not None:
                return minutes
        return None

    def merged_points(self) -> list[dict]:
        """schedule points merged with TS expected times.

        TS locations carry the scheduled times too, so duplicated tiplocs
        (loop services) are matched by tpl AND closest scheduled time.
        """
        ts = list(self.ts_locations)
        merged = []
        for point in self.points:
            entry = dict(point)
            candidates = [
                i for i, loc in enumerate(ts) if loc.get("tpl") == point["tpl"]
            ]
            if candidates:
                if len(candidates) == 1:
                    match = candidates[0]
                else:
                    # pick the candidate whose scheduled time is closest
                    sched_minutes = self._point_time(point)
                    match = min(
                        candidates,
                        key=lambda i: abs(
                            (self._point_time(ts[i]) or 0) - (sched_minutes or 0)
                        ),
                    )
                loc = ts.pop(match)
                entry.update({k: v for k, v in loc.items() if k != "tpl"})
            merged.append(entry)

        # TS locations that didn't match a schedule point (shouldn't happen,
        # but keep them so the train isn't invisible)
        for loc in ts:
            merged.append({"tpl": loc.get("tpl"), "type": "call", **{
                k: v for k, v in loc.items() if k != "tpl"
            }})
        return merged

    def signature(self) -> tuple:
        """cheap change-detection signature"""
        return (
            self.headcode,
            self.toc,
            self.ssd,
            self.cancelled,
            self.cancel_reason,
            self.late_reason,
            tuple(
                (p["tpl"], p["type"], p.get("ptd"), p.get("pta"), p.get("can"))
                for p in self.points
            ),
            tuple(
                (
                    loc.get("tpl"),
                    loc.get("arr_at"), loc.get("arr_et"), loc.get("arr_wet"),
                    loc.get("dep_at"), loc.get("dep_et"), loc.get("dep_wet"),
                    loc.get("pass_at"), loc.get("pass_et"), loc.get("pass_wet"),
                )
                for loc in self.ts_locations
            ),
            tuple(c.get("coachNumber") for c in self.coaches),
        )


class DarwinState:
    def __init__(self):
        self.services: dict[str, ServiceState] = {}

    def apply(self, update: dict):
        rid = update.get("rid")
        if not rid:
            return
        state = self.services.get(rid)
        if state is None:
            state = self.services[rid] = ServiceState()
            state.first_seen = state.last_seen = update.get("_ts")
        state.last_seen = update.get("_ts")

        match update.get("kind"):
            case "schedule":
                state.apply_schedule(update)
            case "ts":
                state.apply_ts(update)
            case "formation":
                state.apply_formation(update)
            case "deactivated":
                state.deactivated = True

    def prune_before(self, cutoff: date):
        """drop services whose service date is before cutoff"""
        for rid, state in list(self.services.items()):
            if state.service_date is not None and state.service_date < cutoff:
                del self.services[rid]
            elif state.service_date is None and not state.headcode:
                # never identified - drop after a day
                if state.first_seen and state.first_seen[:10] < cutoff.isoformat():
                    del self.services[rid]
