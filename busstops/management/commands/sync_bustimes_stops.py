from busstops.bustimes_sync import apply_sync_fields, compact_text
from busstops.models import StopPoint

from ._sync_bustimes import BustimesSyncCommand, api_id, parse_api_datetime, point_from_location


def max_text(value, length):
    return compact_text(value)[:length]


class Command(BustimesSyncCommand):
    help = "Sync stops from the Bustimes API."
    endpoint = "stops/"

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--region",
            help="Optional region id filter, such as L for London.",
        )
        parser.add_argument(
            "--atco-prefix",
            help="Optional ATCO code prefix filter, for example 49 for London stops.",
        )
        parser.add_argument(
            "--atco-code",
            action="append",
            default=[],
            help="Specific ATCO code to sync. Can be supplied multiple times.",
        )

    def get_atco_prefix(self, options):
        prefix = compact_text(options.get("atco_prefix"))
        if prefix:
            return prefix
        if compact_text(options.get("region")).upper() == "L":
            return "49"
        return ""

    def get_query_params(self, options):
        params = super().get_query_params(options)
        region = compact_text(options.get("region"))
        if region:
            params["region"] = region
        atco_prefix = self.get_atco_prefix(options)
        if atco_prefix:
            params["atco_code__startswith"] = atco_prefix
        return params

    def item_matches_region(self, item, options):
        region = compact_text(options.get("region"))
        atco_prefix = self.get_atco_prefix(options)
        atco_code = compact_text(item.get("atco_code"))
        if atco_prefix and atco_code and not atco_code.upper().startswith(
            atco_prefix.upper()
        ):
            return False
        if not region:
            return True
        item_region = compact_text(item.get("region_id"))
        if not item_region:
            return True
        return item_region.upper() == region.upper()

    def values_from_item(self, item):
        name = (
            item.get("common_name")
            or item.get("name")
            or item.get("long_name")
            or item.get("atco_code")
        )
        values = {
            "atco_code": compact_text(item.get("atco_code")),
            "naptan_code": max_text(item.get("naptan_code"), 16),
            "common_name": max_text(name, 48),
            "indicator": max_text(item.get("indicator"), 48),
            "bearing": max_text(item.get("bearing"), 2),
            "stop_type": max_text(item.get("stop_type"), 3),
            "bus_stop_type": max_text(item.get("bus_stop_type"), 3),
            "active": bool(item.get("active", False)),
            "latlong": point_from_location(item.get("location")),
            "created_at": parse_api_datetime(item.get("created_at")),
            "modified_at": parse_api_datetime(item.get("modified_at")),
            "source": self.get_source(),
        }
        if item.get("heading") is not None:
            values["heading"] = int(item["heading"])
        return {key: value for key, value in values.items() if value not in (None, "")}

    def sync_item(self, item, options):
        external_id = api_id(item)
        stop = StopPoint.objects.filter(atco_code__iexact=external_id).first()
        if stop is None:
            stop = StopPoint(atco_code=external_id)
        result = apply_sync_fields(
            instance=stop,
            object_type="stop",
            external_id=external_id,
            values=self.values_from_item(item),
            payload=item,
            dry_run=options["dry_run"],
            force=options["force"],
        )
        return result.created, result.updated, len(result.skipped_fields)

    def iter_exact_atco_items(self, options):
        client = self.get_client(options)
        for atco_code in options.get("atco_code") or []:
            atco_code = compact_text(atco_code)
            for lookup in ("atco_code", "atco_code__iexact"):
                url = client.with_query_params(
                    client.get_endpoint_url(self.endpoint),
                    {lookup: atco_code},
                )
                self.stdout.write(f"Fetching {url}")
                response = client.session.get(url, timeout=client.timeout)
                response.raise_for_status()
                payload = response.json()
                results = payload.get("results", [])
                if results:
                    self.stdout.write(f"Found {len(results)} stop(s) for {atco_code}")
                    yield from results
                    break
            else:
                self.stdout.write(
                    self.style.WARNING(f"No Bustimes stop found for {atco_code}")
                )

    def handle(self, *args, **options):
        created = updated = skipped = 0
        unchanged = 0
        if options.get("atco_code"):
            for item in self.iter_exact_atco_items(options):
                item_created, item_updated, item_skipped = self.sync_item(
                    item, options
                )
                status = "created" if item_created else "updated" if item_updated else "unchanged"
                self.stdout.write(
                    f"{compact_text(item.get('atco_code'))}: "
                    f"{compact_text(item.get('common_name') or item.get('name'))} "
                    f"({status})"
                )
                created += int(item_created)
                updated += int(item_updated)
                skipped += item_skipped
                unchanged += int(
                    not item_created and not item_updated and not item_skipped
                )
            self.print_summary(created, updated, skipped)
            if unchanged:
                self.stdout.write(f"Unchanged {unchanged}")
            return

        progress = self.progress(options)
        for item in self.iter_items_with_progress(options, progress):
            if not self.item_matches_region(item, options):
                progress.tick(skipped=1)
                skipped += 1
                continue
            item_created, item_updated, item_skipped = self.sync_item(
                item, options
            )
            created += int(item_created)
            updated += int(item_updated)
            skipped += item_skipped
            progress.tick(
                created=item_created,
                updated=item_updated,
                skipped=item_skipped,
            )
        self.print_summary(created, updated, skipped)
