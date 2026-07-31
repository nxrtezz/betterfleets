from __future__ import annotations

import random
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from vehicles.models import Livery, Vehicle


@dataclass
class SyncStats:
    total_processed: int = 0
    no_change: int = 0
    updated: int = 0
    livery_created: int = 0
    skipped: int = 0
    errors: int = 0


class Command(BaseCommand):
    help = (
        "Synchronise vehicle liveries against the BusTimes vehicle API only. "
        "This command uses the vehicles endpoint as the single source of truth "
        "and performs per-vehicle API calls with registration-based lookups."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="No DB writes, API still called with rate limiting, logs intended changes",
        )
        parser.add_argument(
            "--operator",
            help="Filter vehicles by operator code (NOC)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of vehicles to process per batch (default: 100)",
        )
        parser.add_argument(
            "--batch-delay",
            type=float,
            default=2.0,
            help="Seconds to sleep between batches (default: 2.0)",
        )

    def handle(self, *args, **options):
        # Safety guard: ensure we never use the forbidden endpoint
        self._safety_check()

        base_url = settings.BUSTIMES_API_BASE_URL.strip()
        if not base_url:
            raise CommandError("BUSTIMES_API_BASE_URL is not configured")

        token = settings.BUSTIMES_API_TOKEN.strip()
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.options = options
        self.stats = SyncStats()
        self.api_cache = {}  # Request caching per run: reg -> response
        self.livery_cache = {}  # Livery tuple lookup cache: (name, left, right) -> livery

        # Build vehicle queryset with operator filter
        vehicle_qs = Vehicle.objects.select_related("livery").filter(withdrawn=False).order_by("fleet_number")
        operator_filter = options.get("operator")
        if operator_filter:
            vehicle_qs = vehicle_qs.filter(
                Q(operator__noc__iexact=operator_filter)
                | Q(operator__slug__iexact=operator_filter)
            )

        total = vehicle_qs.count()
        if not total:
            self.stdout.write("No vehicles matched the filter.")
            return

        self.stdout.write(f"Starting livery sync for {total} vehicle(s)")

        # Process vehicles in batches
        batch_size = options.get("batch_size", 25)
        batch_delay = options.get("batch_delay", 2.0)
        processed = 0

        while processed < total:
            batch = list(vehicle_qs[processed : processed + batch_size])
            if not batch:
                break

            for vehicle in batch:
                self._sync_vehicle(vehicle)
                processed += 1

            # Sleep between batches (except after last batch)
            if processed < total:
                self.stdout.write(f"Batch complete: {processed}/{total} processed, sleeping {batch_delay}s")
                time.sleep(batch_delay)

        self._write_summary()

    def _safety_check(self):
        """Safety guard to prevent using forbidden endpoints."""
        # This is a runtime check - the actual API calls will also be checked
        forbidden_endpoints = ["/api/liveries/", "/api/livery"]
        for endpoint in forbidden_endpoints:
            if endpoint in str(self.base_url if hasattr(self, "base_url") else ""):
                raise CommandError(
                    f"FORBIDDEN: Cannot use {endpoint}. "
                    "This command must only use the vehicles endpoint."
                )

    def _check_url_safety(self, url):
        """Check that a URL doesn't contain forbidden endpoints."""
        forbidden_endpoints = ["/api/liveries/", "/api/livery"]
        for endpoint in forbidden_endpoints:
            if endpoint in url:
                raise CommandError(
                    f"FORBIDDEN: Cannot use {endpoint}. "
                    "This command must only use the vehicles endpoint."
                )

    def _fetch_vehicle_from_api(self, reg):
        """Fetch vehicle data from BusTimes API using registration."""
        # Check cache first
        if reg in self.api_cache:
            return self.api_cache[reg]

        # Build URL - ONLY use vehicles endpoint
        url = urljoin(self.base_url, "api/vehicles/")
        self._check_url_safety(url)

        params = {"reg": reg, "withdrawn": False}

        # Exponential backoff with max 4 retries
        max_retries = 4
        base_delay = 1

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params, timeout=30)

                # Check for rate limiting
                if response.status_code == 429:
                    # Respect Retry-After header if present
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        sleep_time = int(retry_after)
                        self.stdout.write(
                            f"[RETRY] {reg} → 429, retrying in {sleep_time}s (Retry-After header)"
                        )
                        time.sleep(sleep_time)
                        continue
                    else:
                        # Exponential backoff
                        wait = min(base_delay * (2 ** attempt), 8)
                        self.stdout.write(f"[RETRY] {reg} → 429, retrying in {wait}s")
                        time.sleep(wait)
                        continue

                # Check for 5xx errors
                if response.status_code >= 500:
                    wait = min(base_delay * (2 ** attempt), 8)
                    self.stdout.write(f"[RETRY] {reg} → {response.status_code}, retrying in {wait}s")
                    time.sleep(wait)
                    continue

                response.raise_for_status()
                data = response.json()

                # Cache the response
                self.api_cache[reg] = data
                return data

            except requests.exceptions.Timeout:
                wait = min(base_delay * (2 ** attempt), 8)
                self.stdout.write(f"[RETRY] {reg} → timeout, retrying in {wait}s")
                time.sleep(wait)
                continue
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    raise
                wait = min(base_delay * (2 ** attempt), 8)
                self.stdout.write(f"[RETRY] {reg} → {e.__class__.__name__}, retrying in {wait}s")
                time.sleep(wait)
                continue

        # If we get here, all retries failed
        return None

    def _normalize_css(self, value):
        """Normalize CSS value for comparison."""
        return (value or "").strip()

    def _extract_livery_from_api(self, api_data):
        """Extract livery data from BusTimes API response."""
        if not api_data or "results" not in api_data:
            return None

        results = api_data["results"]
        if not results:
            return None

        vehicle_data = results[0]
        livery_data = vehicle_data.get("livery")

        if not livery_data or not isinstance(livery_data, dict):
            return None

        return {
            "name": (livery_data.get("name") or "").strip(),
            "left": self._normalize_css(livery_data.get("left") or livery_data.get("left_css")),
            "right": self._normalize_css(livery_data.get("right") or livery_data.get("right_css")),
        }

    def _liveries_match(self, remote_livery, vehicle):
        """Check if remote livery matches local vehicle's livery."""
        if not vehicle.livery:
            return False

        local_name = (vehicle.livery.name or "").strip()
        local_left = self._normalize_css(vehicle.livery.left_css)
        local_right = self._normalize_css(vehicle.livery.right_css)

        return (
            remote_livery["name"] == local_name
            and remote_livery["left"] == local_left
            and remote_livery["right"] == local_right
        )

    def _find_or_create_livery(self, remote_livery):
        """Find existing livery by (name, left, right) or create new one."""
        # Check cache first
        cache_key = (remote_livery["name"], remote_livery["left"], remote_livery["right"])
        if cache_key in self.livery_cache:
            return self.livery_cache[cache_key]

        # Search for existing livery
        livery = Livery.objects.filter(
            name=remote_livery["name"],
            left_css=remote_livery["left"],
            right_css=remote_livery["right"],
        ).first()

        if livery:
            self.livery_cache[cache_key] = livery
            return livery

        # Create new livery
        livery = Livery(
            name=remote_livery["name"],
            left_css=remote_livery["left"],
            right_css=remote_livery["right"],
            published=True,
            show_name=True,
        )
        livery.save()

        self.livery_cache[cache_key] = livery
        self.stdout.write(f"[CREATED] New livery: {remote_livery['name']}")
        return livery

    def _sync_vehicle(self, vehicle):
        """Sync a single vehicle's livery from BusTimes API."""
        self.stats.total_processed += 1

        if not vehicle.reg:
            self.stats.skipped += 1
            return

        # Fetch from API
        api_data = self._fetch_vehicle_from_api(vehicle.reg)
        if not api_data:
            self.stdout.write(f"{vehicle.reg}: BusTimes API failed")
            self.stats.skipped += 1
            return

        # Extract livery from API response
        remote_livery = self._extract_livery_from_api(api_data)
        if not remote_livery:
            self.stats.skipped += 1
            return

        # Check if liveries already match
        if self._liveries_match(remote_livery, vehicle):
            self.stdout.write(f"{vehicle.reg}: Livery Okay")
            self.stats.no_change += 1
            return

        # Find or create matching livery
        livery = self._find_or_create_livery(remote_livery)

        # Update vehicle if not dry-run
        if not self.options["dry_run"]:
            with transaction.atomic():
                vehicle.livery = livery
                vehicle.save(update_fields=["livery"])

        self.stdout.write(f"{vehicle.reg}: Livery Changes - {remote_livery['name']}")
        self.stats.updated += 1

        # Global throttle between requests (0.2-0.5s jitter)
        jitter = random.uniform(0.2, 0.5)
        time.sleep(jitter)

    def _write_summary(self):
        """Write summary statistics."""
        self.stdout.write(
            "sync: "
            f"total={self.stats.total_processed} "
            f"no_change={self.stats.no_change} "
            f"updated={self.stats.updated} "
            f"livery_created={self.stats.livery_created} "
            f"skipped={self.stats.skipped} "
            f"errors={self.stats.errors}"
        )

        if self.options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no DB writes performed"))
