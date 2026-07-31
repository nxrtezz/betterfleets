from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.signals import post_save

from vehicles.models import Livery
from vehicles.signals import liveries_cache_update


HEX_RE = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?")
DEFAULT_COLOUR = "#808080"


@dataclass
class SyncStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


class Command(BaseCommand):
    help = "Sync all liveries from the Bustimes API"

    protected_fields = {
        "name",
        "colour",
        "colours",
        "left_css",
        "right_css",
        "published",
        "show_name",
    }

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--livery", help="Bustimes livery id/external_id to sync")
        parser.add_argument("--since", help="Incremental watermark where supported by the API")
        parser.add_argument("--limit", type=int, help="Maximum items per paginated API request")

    def handle(self, *args, **options):
        base_url = "https://bustimes.org"
        token = settings.BUSTIMES_API_TOKEN.strip()
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        self.base_url = base_url if base_url.endswith("/") else f"{base_url}/"
        self.options = options
        self.stats = SyncStats()
        self.error_counts = Counter()
        self.error_samples = []

        post_save.disconnect(liveries_cache_update, sender=Livery)
        try:
            with transaction.atomic():
                self.sync_liveries()

                if options["dry_run"] and options.get("livery"):
                    self.refresh_matching_vehicles()

                if options["dry_run"]:
                    transaction.set_rollback(True)
                    self.stdout.write(self.style.WARNING("Dry run: all DB writes rolled back"))
        finally:
            post_save.connect(liveries_cache_update, sender=Livery)

        self.stdout.write(
            "liveries: "
            f"created={self.stats.created} "
            f"updated={self.stats.updated} "
            f"skipped={self.stats.skipped} "
            f"errors={self.stats.errors}"
        )
        if self.error_counts:
            counts = ", ".join(
                f"{name}={count}" for name, count in self.error_counts.most_common(5)
            )
            self.stdout.write(self.style.WARNING(f"error types: {counts}"))
        for sample in self.error_samples[:10]:
            self.stdout.write(self.style.WARNING(f"error sample: {sample}"))

        if options.get("livery") and not options["dry_run"]:
            self.refresh_matching_vehicles()

    def _request_params(self):
        params = {}
        if self.options.get("since"):
            params["since"] = self.options["since"]
        if self.options.get("limit"):
            params["limit"] = self.options["limit"]
        return params

    def _fetch_collection(self, endpoint: str):
        params = self._request_params()
        next_url = urljoin(self.base_url, endpoint.lstrip("/"))

        while next_url:
            response = self.session.get(next_url, params=params or None, timeout=20)
            params = None
            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, list):
                items = payload
                next_url = None
            else:
                items = payload.get("results") or payload.get("items") or payload.get("data") or []
                next_url = payload.get("next")

            for item in items:
                yield item

    @staticmethod
    def _first(*values):
        for value in values:
            if value not in (None, ""):
                return value
        return None

    def _extract_external_id(self, item):
        value = self._first(item.get("external_id"), item.get("id"))
        if value in (None, ""):
            return None
        return str(value)

    def _extract_colour(self, *values):
        for value in values:
            if not value:
                continue
            match = HEX_RE.search(str(value))
            if not match:
                continue
            colour = match.group(0).lower()
            if len(colour) == 4:
                return "#" + "".join(char * 2 for char in colour[1:])
            if len(colour) >= 7:
                return colour[:7]
        return DEFAULT_COLOUR

    def _apply_updates(self, instance, updates):
        dirty = []
        for field, value in updates.items():
            if getattr(instance, "is_manual", False) and field in self.protected_fields:
                continue
            if getattr(instance, field) != value:
                setattr(instance, field, value)
                dirty.append(field)
        return dirty

    def _matches_requested_livery(self, item):
        requested = self.options.get("livery")
        if not requested:
            return True
        requested = str(requested)
        candidates = {
            str(value)
            for value in (
                item.get("external_id"),
                item.get("id"),
                item.get("name"),
            )
            if value not in (None, "")
        }
        return requested in candidates

    def _record_error(self, item, exc=None, reason=None):
        self.stats.errors += 1
        label = reason or exc.__class__.__name__
        self.error_counts[label] += 1
        if len(self.error_samples) >= 10:
            return
        external_id = self._extract_external_id(item)
        name = (item.get("name") or "").strip()
        sample = f"id={external_id or '?'} name={name!r}"
        if exc is not None:
            sample = f"{sample} error={exc.__class__.__name__}: {exc}"
        elif reason:
            sample = f"{sample} error={reason}"
        self.error_samples.append(sample)

    def sync_liveries(self):
        for item in self._fetch_collection("/api/liveries/"):
            try:
                if not self._matches_requested_livery(item):
                    continue

                external_id = self._extract_external_id(item)
                name = (item.get("name") or "").strip()
                if not name:
                    self._record_error(item, reason="missing_name")
                    continue

                left_css = item.get("left") or item.get("left_css") or ""
                right_css = item.get("right") or item.get("right_css") or left_css
                colour = self._extract_colour(item.get("colour"), left_css, right_css)

                livery = None
                if external_id:
                    livery = Livery.objects.filter(external_id=external_id).first()
                if not livery:
                    livery = Livery.objects.filter(name__iexact=name).first()

                values = {
                    "name": name,
                    "colour": colour,
                    "left_css": left_css,
                    "right_css": right_css,
                    "published": True,
                    "show_name": True,
                    "external_id": external_id,
                }

                if not livery:
                    Livery.objects.create(**values)
                    self.stats.created += 1
                    continue

                dirty = self._apply_updates(livery, values)
                if dirty:
                    livery.save()
                    self.stats.updated += 1
                else:
                    self.stats.skipped += 1
            except Exception as exc:
                self._record_error(item, exc=exc)

    def refresh_matching_vehicles(self):
        self.stdout.write(
            self.style.WARNING(
                f"Refreshing vehicles for Bustimes livery {self.options['livery']}"
            )
        )
        call_command(
            "sync_bustimes_fleet",
            livery=self.options["livery"],
            skip_operators=True,
            dry_run=self.options["dry_run"],
            since=self.options.get("since"),
            limit=self.options.get("limit"),
            stdout=self.stdout,
            stderr=self.stderr,
        )
