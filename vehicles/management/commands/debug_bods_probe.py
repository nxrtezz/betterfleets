"""Temporary BODS AVL diagnostic tools.

Probe the Bus Open Data SIRI-VM feed with the configured API key, compare
auth modes, optionally run one importer pass into Redis.

Examples:
  ./manage.py debug_bods_probe
  ./manage.py debug_bods_probe --auth-mode query --sample 5
  ./manage.py debug_bods_probe --auth-mode header --seed-redis --once
  ./manage.py debug_bods_probe --url https://data.bus-data.dft.gov.uk/api/v1/datafeed/123/
  ./manage.py debug_bods_probe --bounding-box "-1.5,51.0,-0.5,52.0"
  ./manage.py debug_bods_probe --redis-status
"""

from __future__ import annotations

import json
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from vehicles.realtime import bods_auth, bods_parser
from vehicles.utils import redis_client

DEFAULT_URL = "https://data.bus-data.dft.gov.uk/api/v1/datafeed/"
AUTH_MODES = ("query", "header", "both")


def _mask_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}…{key[-4:]} (len={len(key)})"


def _extract_location(item: dict) -> tuple[float | None, float | None]:
    try:
        loc = item["MonitoredVehicleJourney"]["VehicleLocation"]
        return float(loc["Longitude"]), float(loc["Latitude"])
    except (KeyError, TypeError, ValueError):
        return None, None


def _sample_summary(item: dict) -> dict[str, Any]:
    mvj = item.get("MonitoredVehicleJourney") or {}
    lon, lat = _extract_location(item)
    return {
        "recorded_at": item.get("RecordedAtTime"),
        "operator": mvj.get("OperatorRef"),
        "line": mvj.get("LineRef") or mvj.get("PublishedLineName"),
        "vehicle": mvj.get("VehicleRef"),
        "destination": mvj.get("DestinationName") or mvj.get("DestinationRef"),
        "lon": lon,
        "lat": lat,
    }


class Command(BaseCommand):
    help = "TEMP: probe BODS AVL API / Redis and optionally seed one importer pass"

    def add_arguments(self, parser):
        parser.add_argument(
            "--auth-mode",
            choices=[*AUTH_MODES, "all", "configured"],
            default="all",
            help="Auth mode to try (default: all modes)",
        )
        parser.add_argument(
            "--url",
            default="",
            help=f"Override feed URL (default: DataSource or {DEFAULT_URL})",
        )
        parser.add_argument(
            "--bounding-box",
            default="",
            help=(
                "BODS boundingBox=minLon,minLat,maxLon,maxLat. "
                "Defaults to settings.BODS_AVL_BOUNDING_BOX. "
                "National feed often returns 403 without a box."
            ),
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=3,
            help="How many vehicle activities to print (default 3)",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=61,
            help="HTTP timeout seconds (default 61)",
        )
        parser.add_argument(
            "--redis-status",
            action="store_true",
            help="Print Redis vehicle_location_locations / sample keys only",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single import_bod_avl.update() pass (writes DB+Redis)",
        )
        parser.add_argument(
            "--seed-redis",
            action="store_true",
            help="Alias for --once (seed Redis via the real importer)",
        )
        parser.add_argument(
            "--seed-redis-light",
            action="store_true",
            help=(
                "TEMP: write up to --limit vehicles straight into Redis "
                "(no Vehicle/Journey DB matching — for map smoke tests)"
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max vehicles for --seed-redis-light (default 50)",
        )
        parser.add_argument(
            "--save-payload",
            default="",
            help="Optional path to write raw (unzipped) XML from first OK response",
        )

    def handle(self, *args, **options):
        self.stdout.write("=== BODS probe (temporary) ===")
        self.stdout.write(f"BODS_API_KEY: {_mask_key(settings.BODS_API_KEY)}")
        self.stdout.write(
            f"BODS_API_AUTH_MODE (settings): {settings.BODS_API_AUTH_MODE!r}"
        )
        self.stdout.write(f"BODS_API_USER_AGENT: {settings.BODS_API_USER_AGENT!r}")
        self.stdout.write(f"REDIS_URL set: {bool(settings.REDIS_URL)}")
        self.stdout.write(f"redis_client: {redis_client is not None}")

        if options["redis_status"] and not any(
            [
                options["once"],
                options["seed_redis"],
                options["seed_redis_light"],
                options["url"],
                options["bounding_box"],
                options["save_payload"],
                options["auth_mode"] != "all",
            ]
        ):
            # Only --redis-status was requested
            self._redis_status()
            return

        if not settings.BODS_API_KEY:
            raise CommandError("BODS_API_KEY is empty — check .env / container env")

        url = options["url"] or self._resolve_url()
        bbox = options["bounding_box"] or getattr(
            settings, "BODS_AVL_BOUNDING_BOX", ""
        )
        self.stdout.write(f"Feed URL: {url}")
        self.stdout.write(f"boundingBox: {bbox or '(none)'}")

        modes = self._modes(options["auth_mode"])
        ok_mode = None
        ok_count = 0
        ok_items: list[dict] = []

        for mode in modes:
            result = self._probe(
                url=url,
                auth_mode=mode,
                bounding_box=bbox,
                timeout=options["timeout"],
                sample=options["sample"],
                save_payload=options["save_payload"] if ok_mode is None else "",
                return_items=options["seed_redis_light"] and ok_mode is None,
            )
            if result["ok"]:
                ok_mode = mode
                ok_count = result["vehicle_count"]
                if result.get("items"):
                    ok_items = result["items"]

        if options["seed_redis_light"]:
            if not ok_items:
                raise CommandError("No items to seed; probe failed or returned empty")
            self._seed_redis_light(ok_items, limit=options["limit"])

        if options["redis_status"] or options["seed_redis_light"]:
            self._redis_status()

        if options["once"] or options["seed_redis"]:
            if ok_mode is None and options["auth_mode"] == "all":
                raise CommandError("No auth mode returned a usable feed; not seeding")
            self._run_once(auth_mode=ok_mode or settings.BODS_API_AUTH_MODE)
            self._redis_status()

        if ok_mode is None:
            self.stderr.write(
                self.style.ERROR(
                    "All probes failed. Check API key, auth mode, and feed URL/subscription."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Working auth mode: {ok_mode} ({ok_count} VehicleActivity items)"
                )
            )

    def _modes(self, choice: str) -> list[str]:
        if choice == "all":
            return list(AUTH_MODES)
        if choice == "configured":
            return [settings.BODS_API_AUTH_MODE or "query"]
        return [choice]

    def _resolve_url(self) -> str:
        try:
            from busstops.models import DataSource

            source = DataSource.objects.filter(name="Bus Open Data").first()
            if source and source.url:
                return source.url
        except Exception as exc:  # pragma: no cover - DB may be down during probe
            self.stderr.write(f"DataSource lookup skipped: {exc}")
        return DEFAULT_URL

    def _probe(
        self,
        *,
        url: str,
        auth_mode: str,
        bounding_box: str,
        timeout: float,
        sample: int,
        save_payload: str,
        return_items: bool = False,
    ) -> dict[str, Any]:
        self.stdout.write("")
        self.stdout.write(f"--- auth_mode={auth_mode} ---")
        kwargs = bods_auth.get_bods_request_kwargs(auth_mode=auth_mode)
        params = dict(kwargs.get("params") or {})
        if bounding_box:
            params["boundingBox"] = bounding_box

        try:
            response = requests.get(
                url,
                params=params or None,
                headers=kwargs.get("headers"),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            self.stderr.write(self.style.ERROR(f"Request error: {exc}"))
            return {"ok": False, "vehicle_count": 0}

        ctype = response.headers.get("content-type", "")
        self.stdout.write(f"status={response.status_code} content-type={ctype!r}")
        self.stdout.write(f"bytes={len(response.content)}")

        # Never print secrets that might appear in Location query strings
        if "www-authenticate" in response.headers:
            self.stdout.write(
                f"www-authenticate={response.headers.get('www-authenticate')!r}"
            )

        if not response.ok:
            preview = response.content[:300]
            try:
                preview_text = preview.decode("utf-8", errors="replace")
            except Exception:
                preview_text = repr(preview)
            self.stderr.write(self.style.ERROR(f"body preview: {preview_text!r}"))
            return {"ok": False, "vehicle_count": 0}

        data = bods_parser.maybe_unzip_payload(response.content, ctype)
        if save_payload:
            with open(save_payload, "wb") as fh:
                fh.write(data)
            self.stdout.write(f"wrote unzipped payload → {save_payload}")

        try:
            root, items = bods_parser.parse_vehicle_activity_xml(data)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"XML parse failed: {exc}"))
            preview = data[:200]
            self.stderr.write(f"payload preview: {preview!r}")
            return {"ok": False, "vehicle_count": 0}

        ns = bods_parser.SIRI_NS
        service_delivery = root.find(f"{{{ns}}}ServiceDelivery")
        response_ts = None
        if service_delivery is not None:
            response_ts = service_delivery.findtext(f"{{{ns}}}ResponseTimestamp")

        with_coords = sum(1 for item in items if _extract_location(item)[0] is not None)
        self.stdout.write(
            self.style.SUCCESS(
                f"OK: VehicleActivity={len(items)} with_coords={with_coords} "
                f"ResponseTimestamp={response_ts!r}"
            )
        )

        for item in items[: max(0, sample)]:
            self.stdout.write(json.dumps(_sample_summary(item), default=str))

        result: dict[str, Any] = {
            "ok": True,
            "vehicle_count": len(items),
            "with_coords": with_coords,
        }
        if return_items:
            result["items"] = items
        return result

    def _seed_redis_light(self, items: list[dict], limit: int = 50):
        self.stdout.write("")
        self.stdout.write(f"=== light Redis seed (limit={limit}) ===")
        if not redis_client:
            raise CommandError("redis_client is None")

        # Use high synthetic IDs so we don't collide with real Vehicle PKs often
        base_id = 9_000_000
        written = 0
        pipe = redis_client.pipeline(transaction=False)
        geoadd: list[float | int] = []

        for item in items:
            if written >= limit:
                break
            lon, lat = _extract_location(item)
            if lon is None or lat is None:
                continue
            summary = _sample_summary(item)
            vehicle_id = base_id + written
            payload = {
                "id": vehicle_id,
                "journey_id": vehicle_id,  # synthetic
                "coordinates": [lon, lat],
                "heading": None,
                "datetime": summary.get("recorded_at"),
                "destination": summary.get("destination"),
                "service": {"line_name": summary.get("line") or "?"},
                # Inline vehicle so /vehicles.json does not need a DB row
                "vehicle": {
                    "id": vehicle_id,
                    "name": summary.get("vehicle") or str(vehicle_id),
                    "fleet_code": summary.get("vehicle") or "",
                    "operator": {"noc": summary.get("operator"), "name": summary.get("operator")},
                },
                "debug_bods_light": True,
                "operator": summary.get("operator"),
                "vehicle_ref": summary.get("vehicle"),
            }
            pipe.set(
                f"vehicle{vehicle_id}",
                json.dumps(payload),
                ex=900,
            )
            geoadd.extend([lon, lat, vehicle_id])
            if summary.get("operator"):
                pipe.sadd(f"operator{summary['operator']}vehicles", vehicle_id)
            written += 1

        if geoadd:
            pipe.geoadd("vehicle_location_locations", geoadd)
        pipe.execute()
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {written} synthetic vehicles to Redis "
                f"(ids {base_id}…{base_id + max(written - 1, 0)})"
            )
        )

    def _run_once(self, auth_mode: str):
        self.stdout.write("")
        self.stdout.write(f"=== one-shot import_bod_avl.update() (auth={auth_mode}) ===")
        # Temporarily align settings with the mode that worked
        previous = settings.BODS_API_AUTH_MODE
        settings.BODS_API_AUTH_MODE = auth_mode
        try:
            from vehicles.management.commands.import_bod_avl import Command as BodCommand

            command = BodCommand()
            # __init__ already created/loaded DataSource and session headers
            wait = command.update()
            self.stdout.write(self.style.SUCCESS(f"update() finished (next wait={wait})"))
        except Exception as exc:
            raise CommandError(f"import_bod_avl update failed: {exc}") from exc
        finally:
            settings.BODS_API_AUTH_MODE = previous

    def _redis_status(self):
        self.stdout.write("")
        self.stdout.write("=== Redis status ===")
        if not redis_client:
            self.stderr.write(self.style.ERROR("redis_client is None (REDIS_URL missing?)"))
            return
        try:
            geo_count = redis_client.zcard("vehicle_location_locations")
            # Sample a few vehicle keys without scanning the whole DB
            vehicle_ids = redis_client.zrange("vehicle_location_locations", 0, 4)
            self.stdout.write(f"vehicle_location_locations members: {geo_count}")
            self.stdout.write(f"sample ids: {vehicle_ids}")
            if vehicle_ids:
                keys = [f"vehicle{vid.decode() if isinstance(vid, bytes) else vid}" for vid in vehicle_ids]
                values = redis_client.mget(keys)
                for key, raw in zip(keys, values):
                    if not raw:
                        self.stdout.write(f"  {key}: MISSING")
                        continue
                    try:
                        payload = json.loads(raw)
                        self.stdout.write(
                            f"  {key}: coords={payload.get('coordinates')} "
                            f"datetime={payload.get('datetime')} "
                            f"service={payload.get('service')}"
                        )
                    except json.JSONDecodeError:
                        self.stdout.write(f"  {key}: (non-json, {len(raw)} bytes)")
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Redis error: {exc}"))
