import re
from uuid import uuid4
from http import HTTPStatus

from django.http import HttpResponse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers

from whitenoise.middleware import WhiteNoiseMiddleware

SITE_USAGE_CACHE_KEY = "site-usage-tracker"
SITE_USAGE_COOKIE = "bf_usage_id"
SITE_USAGE_RETENTION_SECONDS = 60 * 60 * 24 * 7
_SITE_USAGE_MEMORY = {}


def _prune_site_usage(entries, now_ts):
    cutoff = now_ts - SITE_USAGE_RETENTION_SECONDS
    return {
        identifier: entry
        for identifier, entry in entries.items()
        if entry.get("last_seen", 0) >= cutoff
    }


def _get_site_usage_cache():
    from django.core.cache import cache

    if cache.__class__.__name__ == "DummyCache":
        return None
    return cache


def get_site_usage_entries():
    now_ts = timezone.now().timestamp()
    cache = _get_site_usage_cache()
    if cache is None:
        global _SITE_USAGE_MEMORY
        _SITE_USAGE_MEMORY = _prune_site_usage(_SITE_USAGE_MEMORY, now_ts)
        return _SITE_USAGE_MEMORY

    entries = _prune_site_usage(cache.get(SITE_USAGE_CACHE_KEY, {}), now_ts)
    cache.set(SITE_USAGE_CACHE_KEY, entries, SITE_USAGE_RETENTION_SECONDS)
    return entries


class SiteUsageTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if (
            request.path.startswith("/static/")
            or request.path.startswith("/media/")
            or request.path == "/up"
        ):
            return response

        cookie_id = request.COOKIES.get(SITE_USAGE_COOKIE)
        if not cookie_id:
            cookie_id = uuid4().hex
            response.set_cookie(
                SITE_USAGE_COOKIE,
                cookie_id,
                max_age=SITE_USAGE_RETENTION_SECONDS,
                httponly=True,
                samesite="Lax",
            )

        if request.user.is_authenticated:
            identifier = f"user:{request.user.pk}"
        else:
            identifier = f"anon:{cookie_id}"

        now_ts = timezone.now().timestamp()
        entries = get_site_usage_entries().copy()
        entries[identifier] = {
            "last_seen": now_ts,
            "authenticated": bool(request.user.is_authenticated),
            "staff": bool(request.user.is_staff),
        }
        cache = _get_site_usage_cache()
        if cache is None:
            global _SITE_USAGE_MEMORY
            _SITE_USAGE_MEMORY = entries
        else:
            cache.set(SITE_USAGE_CACHE_KEY, entries, SITE_USAGE_RETENTION_SECONDS)

        return response


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/up":
            # bypass ALLOWED_HOSTS check
            response = HttpResponse("up!")
        else:
            response = self.get_response(request)

        return response


class WhiteNoiseWithFallbackMiddleware(WhiteNoiseMiddleware):
    def immutable_file_test(self, path, url):
        # ensure that cache-control headers are added
        # for files with hashes added by parcel e.g. "dist/js/BigMap.19ec75b5.js"
        if re.match(r"^.+\.[0-9a-f]{8,12}\..+$", url):
            return True
        return super().immutable_file_test(path, url)

    # https://github.com/evansd/whitenoise/issues/245
    def __call__(self, request):
        response = super().__call__(request)
        if response.status_code == HTTPStatus.NOT_FOUND and request.path.startswith(
            self.static_prefix
        ):
            add_never_cache_headers(response)
        return response


def pin_db_middleware(get_response):
    from multidb.pinning import pin_this_thread, unpin_this_thread

    def middleware(request):
        if (
            request.method == "POST"
            or request.path.startswith("/admin/")
            or request.path.startswith("/accounts/")
            or "/edit" in request.path
        ):
            pin_this_thread()
        else:
            unpin_this_thread()
        return get_response(request)

    return middleware
