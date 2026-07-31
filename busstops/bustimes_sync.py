from __future__ import annotations

import datetime
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .data_changes import record_applied_change, record_pending_change
from .models import BustimesSyncState


DEFAULT_BUSTIMES_API_BASE = "https://bustimes.org/api/"


class BustimesApiClient:
    def __init__(self, base_url: str | None = None, *, timeout: int = 30):
        base_url = base_url or getattr(
            settings, "BUSTIMES_API_BASE_URL", DEFAULT_BUSTIMES_API_BASE
        )
        self.base_url = self.normalise_base_url(base_url)
        self.timeout = timeout
        self.session = requests.Session()
        self._api_index: dict[str, str] | None = None

    @staticmethod
    def normalise_base_url(base_url: str) -> str:
        base_url = (base_url or DEFAULT_BUSTIMES_API_BASE).strip()
        parsed = urlparse(base_url)
        path = parsed.path.rstrip("/")
        if not path.endswith("/api"):
            path = f"{path}/api" if path else "/api"
        return parsed._replace(path=f"{path}/", params="", query="", fragment="").geturl()

    def get_api_index(self) -> dict[str, str]:
        if self._api_index is None:
            response = self.session.get(self.base_url, timeout=self.timeout)
            response.raise_for_status()
            self._api_index = response.json()
        return self._api_index

    def get_endpoint_url(self, endpoint: str) -> str:
        endpoint = endpoint.strip("/")
        try:
            return self.get_api_index()[endpoint]
        except (KeyError, requests.RequestException, ValueError):
            return urljoin(self.base_url, f"{endpoint}/")

    @staticmethod
    def with_query_params(url: str, params: dict[str, Any] | None = None) -> str:
        if not params:
            return url
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        for key, value in params.items():
            if value in (None, ""):
                continue
            query[str(key)] = str(value)
        return urlunparse(parsed._replace(query=urlencode(query)))

    def iter_pages(
        self,
        endpoint: str,
        *,
        limit: int = 100,
        params: dict[str, Any] | None = None,
    ):
        url = self.get_endpoint_url(endpoint)
        query_params = {"limit": limit}
        if params:
            query_params.update(params)
        url = self.with_query_params(url, query_params)

        while url:
            max_retries = 5
            
            for attempt in range(max_retries):
                try:
                    response = self.session.get(url, timeout=self.timeout)
                    response.raise_for_status()
                    payload = response.json()
                    yield payload, url
                    url = payload.get("next")
                    break
                except requests.HTTPError as e:
                    if e.response.status_code == 429:
                        if attempt < max_retries - 1:
                            wait_time = 2 + (attempt * 2)
                            time.sleep(wait_time)
                        else:
                            raise
                    else:
                        raise

    def iter_results(
        self,
        endpoint: str,
        *,
        limit: int = 100,
        max_items: int | None = None,
        params: dict[str, Any] | None = None,
    ):
        seen = 0
        for payload, _url in self.iter_pages(endpoint, limit=limit, params=params):
            for item in payload.get("results", []):
                yield item
                seen += 1
                if max_items and seen >= max_items:
                    return
            url = payload.get("next")


def get_external_id(item: dict[str, Any]) -> str:
    value = item.get("id") or item.get("atco_code") or item.get("slug")
    return str(value)


def compact_text(value: Any) -> str:
    return str(value or "").strip()


def compact_registration(value: Any) -> str:
    return compact_text(value).upper().replace(" ", "")


def model_value(value: Any) -> Any:
    if hasattr(value, "pk"):
        return str(value.pk) if value.pk is not None else None
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if hasattr(value, "wkt"):
        return value.wkt
    return value


def current_value(instance: Any, field: str) -> Any:
    try:
        model_field = instance._meta.get_field(field)
    except Exception:
        model_field = None
    if model_field is not None and getattr(model_field, "is_relation", False):
        value = getattr(instance, model_field.attname)
        return str(value) if value is not None else None
    value = getattr(instance, field)
    return model_value(value)


def has_model_field(instance: Any, field: str) -> bool:
    try:
        instance._meta.get_field(field)
    except Exception:
        return hasattr(instance, field)
    return True


@dataclass
class SyncResult:
    created: bool = False
    updated: bool = False
    skipped_fields: tuple[str, ...] = ()


@transaction.atomic
def apply_sync_fields(
    *,
    instance: Any,
    object_type: str,
    external_id: str,
    values: dict[str, Any],
    payload: dict[str, Any],
    dry_run: bool = False,
    force: bool = False,
    source: str | None = None,
) -> SyncResult:
    if dry_run:
        state = BustimesSyncState.objects.filter(
            object_type=object_type,
            external_id=str(external_id),
        ).first()
    else:
        state, _ = BustimesSyncState.objects.select_for_update().get_or_create(
            object_type=object_type,
            external_id=str(external_id),
        )
    last_fields = dict(state.last_fields or {}) if state else {}
    protected_fields = set(state.protected_fields or []) if state else set()
    changed_fields: list[str] = []
    skipped_fields: list[str] = []
    applied_changes: dict[str, dict[str, Any]] = {}
    pending_changes: dict[str, dict[str, Any]] = {}
    created = instance.pk is None

    for field, value in values.items():
        if not has_model_field(instance, field):
            continue

        target = model_value(value)
        current = current_value(instance, field)
        previous = last_fields.get(field)

        if (
            not force
            and previous is not None
            and current != previous
            and current != target
        ):
            protected_fields.add(field)
            skipped_fields.append(field)
            pending_changes[field] = {
                "from": current,
                "to": target,
                "previous_import": previous,
            }
            continue

        if current != target:
            setattr(instance, field, value)
            changed_fields.append(field)
            applied_changes[field] = {
                "from": current,
                "to": target,
                "previous_import": previous,
            }

        last_fields[field] = target
        protected_fields.discard(field)

    if not dry_run:
        if created or changed_fields:
            instance.save()
            if applied_changes:
                record_applied_change(
                    source=source or f"bustimes_sync:{object_type}",
                    instance=instance,
                    operation="create" if created else "update",
                    changes=applied_changes,
                    payload=payload,
                )
        if pending_changes and instance.pk:
            record_pending_change(
                source=source or f"bustimes_sync:{object_type}",
                instance=instance,
                operation="update",
                changes=pending_changes,
                payload=payload,
                reason="Manual user data differs from the last imported value.",
            )
        state.local_model = instance._meta.label_lower
        state.local_pk = str(instance.pk or "")
        state.last_fields = last_fields
        state.last_payload = {
            key: model_value(value) for key, value in (payload or {}).items()
        }
        state.protected_fields = sorted(protected_fields)
        state.last_synced_at = timezone.now()
        state.save()

    return SyncResult(
        created=created,
        updated=bool(changed_fields),
        skipped_fields=tuple(skipped_fields),
    )
