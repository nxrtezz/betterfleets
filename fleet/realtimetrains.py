"""Small server-side client for the Realtime Trains next-generation API."""

from __future__ import annotations

from datetime import date, datetime, time

import requests
from django.conf import settings


class RTTError(RuntimeError):
    """An actionable Realtime Trains API failure."""


class RTTClient:
    def __init__(self, token: str | None = None):
        self.access_token = (
            token
            or settings.RTT_API_ACCESS_TOKEN
            or settings.RTT_API_TOKEN
        )
        self.refresh_token = settings.RTT_API_REFRESH_TOKEN
        if not self.access_token and not self.refresh_token:
            raise RTTError(
                "Configure RTT_API_ACCESS_TOKEN or the issued "
                "RTT_API_REFRESH_TOKEN on the server. The API portal token ID "
                "cannot authenticate API requests."
            )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "BetterFleets rail replacement timetable/1.0",
            }
        )

    def _request(self, path, params=None, token=None):
        request_params = dict(params or {})
        if settings.RTT_API_VERSION:
            request_params["version"] = settings.RTT_API_VERSION
        headers = {"Authorization": f"Bearer {token or self.access_token}"}
        try:
            return self.session.get(
                f"{settings.RTT_API_BASE_URL}{path}",
                params=request_params,
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RTTError(f"RTT request failed: {exc}") from exc

    def _exchange_refresh_token(self):
        if not self.refresh_token:
            raise RTTError(
                "RTT_API_TOKEN is a portal token ID, not an issued credential. "
                "Set RTT_API_ACCESS_TOKEN to the issued access token or "
                "RTT_API_REFRESH_TOKEN to the issued refresh token."
            )
        response = self._request("/api/get_access_token", token=self.refresh_token)
        if response.status_code >= 400:
            detail = response.text[:300].strip()
            raise RTTError(
                "RTT token exchange failed with HTTP "
                f"{response.status_code}: {detail}"
            )
        try:
            access_token = response.json().get("token")
        except ValueError as exc:
            raise RTTError("RTT token exchange returned invalid JSON.") from exc
        if not access_token:
            raise RTTError("RTT token exchange returned no access token.")
        self.access_token = access_token

    def _get(self, path, params=None):
        response = self._request(path, params, token=self.access_token)
        if response.status_code == 401 and "token ID" in response.text:
            self._exchange_refresh_token()
            response = self._request(path, params)
        if response.status_code == 204:
            return {}
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "later")
            raise RTTError(f"RTT rate limit reached; retry after {retry_after} seconds.")
        if response.status_code >= 400:
            detail = response.text[:300].strip()
            raise RTTError(f"RTT returned HTTP {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise RTTError("RTT returned invalid JSON.") from exc

    def info(self):
        return self._get("/api/info")

    def stops(self):
        return self._get("/data/stops").get("stops", [])

    def location_services(self, code: str, service_date: date):
        start = datetime.combine(service_date, time.min).isoformat()
        end = datetime.combine(service_date, time(23, 59, 59)).isoformat()
        payload = self._get(
            "/gb-nr/location",
            {
                "code": code,
                "timeFrom": start,
                "timeTo": end,
                "detailed": "false",
            },
        )
        return payload.get("services", [])

    def service(self, unique_identity: str):
        payload = self._get(
            "/gb-nr/service",
            {"uniqueIdentity": unique_identity, "detailed": "false"},
        )
        return payload.get("service") or {}
