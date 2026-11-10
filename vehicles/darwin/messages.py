"""Parse Darwin Push Port v16 Pport XML messages into plain dicts.

Real message shapes (captured from the live feed):

<uR updateOrigin="Workstation">
  <schedule rid="202611107189015" uid="G89015" trainId="1B41"
            rsid="TP514500" ssd="2026-11-10" toc="NT" trainCat="XX">
    <OR wtd="19:24" ptd="19:24" tpl="YORK" act="TB"/>
    <IP wta="19:34:30" wtd="19:35:30" tpl="CHFN" act="T " pta="19:35" ptd="19:35"/>
    <PP wtp="19:41" tpl="MCKLFLD"/>
    <DT wta="20:01" tpl="LVRPLSH" act="TF" pta="20:01"/>
    <cancelReason>811</cancelReason>
  </schedule>
</uR>

<uR updateOrigin="Darwin">
  <TS rid="202611117637879" uid="L37879" ssd="2026-11-11">
    <Location tpl="BHAMMRS" wtd="00:16">
      <dep et="00:16" src="Darwin"/>
      <plat platsup="true">3</plat>
    </Location>
    <Location tpl="BHAMMSS" wta="00:18">
      <arr et="00:18" src="Darwin"/>
    </Location>
  </TS>
</uR>

<uR updateOrigin="CIS">
  <scheduleFormations rid="202611106737227">
    <formation fid="202611106737227-001">
      <coaches>
        <coach coachNumber="1" coachClass="Standard"/>
      </coaches>
    </formation>
  </scheduleFormations>
</uR>
"""

import xml.etree.ElementTree as ET

# local-name -> canonical point type, in document order they are the calling points
POINT_TYPES = {"OR": "origin", "DT": "destination", "IP": "call", "PP": "pass"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, names: set[str]):
    for child in element:
        if _local(child.tag) in names:
            yield child


def _parse_time(value: str | None) -> str | None:
    if not value:
        return None
    # times are "HH:MM" or "HH:MM:SS", can exceed 24:00
    parts = value.split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return None
    if m > 59 or s > 59:
        return None
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_schedule(element: ET.Element) -> dict | None:
    """<schedule> element -> service identity + ordered calling points"""
    rid = element.get("rid")
    if not rid:
        return None

    points = []
    for loc in element:
        tag = _local(loc.tag)
        point_type = POINT_TYPES.get(tag)
        if point_type is None:
            continue
        point = {
            "tpl": loc.get("tpl"),
            "type": point_type,
            "wta": _parse_time(loc.get("wta")),
            "wtd": _parse_time(loc.get("wtd")),
            "wtp": _parse_time(loc.get("wtp")),
            "pta": _parse_time(loc.get("pta")),
            "ptd": _parse_time(loc.get("ptd")),
            "act": loc.get("act"),
            "cancelled": loc.get("can") == "true",
            "fid": loc.get("fid"),
        }
        if loading := loc.get("avgLoading"):
            try:
                point["avg_loading"] = int(loading)
            except ValueError:
                pass
        points.append(point)

    # cancelReason is namespaced in real messages
    cancel_reason = None
    for child in element:
        if _local(child.tag) == "cancelReason":
            cancel_reason = (child.text or "").strip() or None
            break

    # a service is only fully cancelled when its origin or destination call
    # is cancelled - individual IP/PP points can be can="true" for partial
    # cancellations while the train still runs
    cancelled = any(
        p["type"] in {"origin", "destination"} and p["cancelled"]
        for p in points
    )

    is_passenger = element.get("isPassengerSvc", "true").lower() != "false"

    return {
        "kind": "schedule",
        "rid": rid,
        "uid": element.get("uid"),
        "headcode": element.get("trainId"),
        "rsid": element.get("rsid"),
        "ssd": element.get("ssd"),
        "toc": element.get("toc"),
        "train_cat": element.get("trainCat"),
        "is_passenger": is_passenger,
        "cancelled": cancelled,
        "cancel_reason": cancel_reason,
        "points": points,
    }


def parse_train_status(element: ET.Element) -> dict | None:
    """<TS> element -> rid + ordered Location updates with expected times"""
    rid = element.get("rid")
    if not rid:
        return None

    locations = []
    for loc in _children(element, {"Location"}):
        update = {"tpl": loc.get("tpl")}
        for name in ("wta", "wtd", "wtp", "pta", "ptd"):
            if value := _parse_time(loc.get(name)):
                update[name] = value

        for kind in ("arr", "dep", "pass"):
            for child in _children(loc, {kind}):
                # at = actual/reported time, et = estimate, wet = working estimate
                for attr in ("at", "et", "wet"):
                    if value := _parse_time(child.get(attr)):
                        update[f"{kind}_{attr}"] = value
                for attr in ("src", "srcInst", "atClass"):
                    if value := child.get(attr):
                        update[f"{kind}_{attr}"] = value
                if child.get("delayed") == "true":
                    update[f"{kind}_delayed"] = True
                if child.get("atRemoved") == "true":
                    update[f"{kind}_at_removed"] = True

        for child in _children(loc, {"plat"}):
            update["platform"] = (child.text or "").strip() or None
            if child.get("platsup") == "true" or child.get("cisPlatsup") == "true":
                update["platform_suppressed"] = True

        for child in _children(loc, {"length"}):
            try:
                update["length"] = int((child.text or "").strip())
            except ValueError:
                pass

        for child in _children(loc, {"LateReason"}):
            update["late_reason"] = (child.text or "").strip() or None

        locations.append(update)

    late_reason = None
    for child in element:
        if _local(child.tag) == "LateReason":
            late_reason = (child.text or "").strip() or None

    return {
        "kind": "ts",
        "rid": rid,
        "uid": element.get("uid"),
        "ssd": element.get("ssd"),
        "late_reason": late_reason,
        "locations": locations,
    }


def parse_formations(element: ET.Element) -> dict | None:
    """<scheduleFormations> -> coach/unit details for a rid"""
    rid = element.get("rid")
    if not rid:
        return None

    coaches = []
    for coach in element.iter():
        if _local(coach.tag) == "coach":
            coaches.append(dict(coach.attrib))

    return {"kind": "formation", "rid": rid, "coaches": coaches}


def parse_pport(xml_bytes: bytes) -> list[dict]:
    """parse a (decompressed) Pport message -> list of update dicts"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    if _local(root.tag) != "Pport":
        return []

    updates = []
    for uR in _children(root, {"uR"}):
        origin = uR.get("updateOrigin")
        for child in uR:
            tag = _local(child.tag)
            if tag == "schedule":
                if schedule := parse_schedule(child):
                    schedule["update_origin"] = origin
                    updates.append(schedule)
            elif tag == "TS":
                if ts := parse_train_status(child):
                    ts["update_origin"] = origin
                    updates.append(ts)
            elif tag == "scheduleFormations":
                if formation := parse_formations(child):
                    formation["update_origin"] = origin
                    updates.append(formation)
            # association, formationLoading, station messages, alerts,
            # train order, alarms etc are ignored for now
    return updates
