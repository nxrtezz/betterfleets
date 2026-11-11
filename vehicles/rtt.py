"""Realtime Trains (RTT) Next-Generation API client.

Used for rolling stock allocations - the unit numbers (TOPS identities)
that Darwin Push Port doesn't publish for open-data accounts.

Auth: a long-life refresh token is exchanged for a short-lived access
token via GET /api/get_access_token (refresh token as Bearer).
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://data.rtt.io"


class RttError(Exception):
    pass


class RttClient:
    def __init__(self, refresh_token: str | None = None):
        self.refresh_token = refresh_token or os.environ.get("RTT_REFRESH_TOKEN")
        self._access_token = None
        self._token_expiry = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.refresh_token)

    def _refresh(self):
        req = urllib.request.Request(
            f"{BASE_URL}/api/get_access_token",
            headers={"Authorization": f"Bearer {self.refresh_token}"},
        )
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except urllib.error.HTTPError as e:
            raise RttError(f"token refresh failed: {e.code} {e.read()[:200]}")
        self._access_token = data["token"]
        try:
            self._token_expiry = datetime.fromisoformat(
                data["validUntil"].replace("Z", "+00:00")
            ).timestamp()
        except (KeyError, ValueError):
            self._token_expiry = time.time() + 600
        return self._access_token

    def get(self, path: str) -> dict:
        if not self.configured:
            raise RttError("RTT_REFRESH_TOKEN not configured")
        if not self._access_token or time.time() > self._token_expiry - 30:
            self._refresh()
        req = urllib.request.Request(
            BASE_URL + path,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 401:  # token expired early - refresh once and retry
                self._access_token = None
                self._refresh()
                req = urllib.request.Request(
                    BASE_URL + path,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
                return json.loads(urllib.request.urlopen(req, timeout=30).read())
            raise RttError(f"{path}: {e.code} {e.read()[:200]}")

    def service(self, identity: str, departure_date: str) -> dict:
        """service detail incl. allocationData; identity is the Darwin uid"""
        return self.get(
            f"/gb-nr/service?identity={identity}"
            f"&departureDate={departure_date}&detailed=true"
        ).get("service", {})


def allocation_summary(service: dict) -> dict | None:
    """pull the rolling stock allocation out of a /gb-nr/service response"""
    allocation = next(iter(service.get("allocationData") or []), None)
    if not allocation:
        return None
    units = []
    for item in allocation.get("allocationItems") or []:
        if item.get("identity"):
            units.append(
                {
                    "tops": item["identity"],
                    "cars": item.get("numberOfVehicles") or 1,
                    "in_reverse": bool(item.get("inReverse")),
                }
            )
    return {
        "tops": units[0]["tops"] if units else None,
        "units": units,
        "leading_class": allocation.get("leadingClass"),
        "passenger_vehicles": allocation.get("passengerVehicles"),
    }


def tops_display_name(identity: str, leading_class: str | None) -> str:
    """format a TOPS stock number for display: 700114 + class 700 -> '700 114'"""
    if leading_class and identity.startswith(leading_class):
        return f"{leading_class} {identity[len(leading_class):]}"
    return identity
