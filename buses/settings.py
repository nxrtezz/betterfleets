"""These settings rely on various environment variables being set"""

import os
import re
import sys
from pathlib import Path
from warnings import filterwarnings

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv_file(path):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


load_dotenv_file(BASE_DIR / ".env")


def env_list(name, default=""):
    raw_value = os.environ.get(name, default) or ""
    return [item for item in re.split(r"[\s,]+", raw_value) if item]

BUSTIMES_REFERENCE_DIR = BASE_DIR / "bustimes.org"
if BUSTIMES_REFERENCE_DIR.exists():
    sys.path.append(str(BUSTIMES_REFERENCE_DIR))
else:
    BUSTIMES_REFERENCE_DIR = BASE_DIR / "bustimes_REFERENCE"
    if BUSTIMES_REFERENCE_DIR.exists():
        sys.path.append(str(BUSTIMES_REFERENCE_DIR))
SECRET_KEY = os.environ.get("SECRET_KEY", "")
ALLOWED_HOSTS = list(
    dict.fromkeys(
        env_list("ALLOWED_HOSTS", "127.0.0.1 localhost eeveeit.uk")
        + ["127.0.0.1", "localhost", "eeveeit.uk"]
    )
)

CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        env_list(
            "CSRF_TRUSTED_ORIGINS",
            "https://bustimes.org https://eeveeit.uk",
        )
        + ["https://bustimes.org", "https://eeveeit.uk"]
    )
)
CSRF_FAILURE_VIEW = "busstops.views.csrf_failure"

TEST = "test" in sys.argv or "pytest" in sys.argv[0]
DEBUG = bool(os.environ.get("DEBUG", False))

DEFAULT_FROM_EMAIL = '"bustimes.org" <bustimes.org@bustimes.org>'

EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_PORT = 465
EMAIL_USE_SSL = True
EMAIL_TIMEOUT = 10
if TEST:
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
elif DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INSTALLED_APPS = [
    # "daphne",
    "accounts",
    "busstops.apps.BusstopsConfig",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "django.contrib.sitemaps",
    "django.contrib.humanize",
    "bustimes",
    "disruptions",
    "fares",
    "fleet",
    "vehicles",
    "vehicle_history",
    "tools",
    "email_obfuscator.apps.EmailObfuscatorConfig",
    "photos",
    "rest_framework",
    "django_filters",
    "simple_history",
    "huey.contrib.djhuey",
    "corsheaders",
    "turnstile",
    "django_http_compression",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.discord",
    "allauth.socialaccount.providers.github",
    "allauth.mfa",
    "allauth.mfa.webauthn",
    "service_requests.apps.ServiceRequestsConfig",
    "favourites",
    "service_logging",
]


MIDDLEWARE = [
    "busstops.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django_http_compression.middleware.HttpCompressionMiddleware",
    "busstops.middleware.WhiteNoiseWithFallbackMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "busstops.request_context.CurrentRequestMiddleware",
    "busstops.middleware.SiteUsageTrackingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    # "vehicles.middleware.UnicodeDecodeErrorMiddleware",  # Temporarily disabled
]

# Stadia Maps tiles require we send at least the origin in cross-origin requests.
# For same-origin requests, the full referrer is useful (e.g. for the contact form)
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

SECURE_BROWSER_XSS_FILTER = True
SECURE_PROXY_SSL_HEADER = ("HTTP_CF_VISITOR", '{"scheme":"https"}')
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_REDIRECT_EXEMPT = [r"^version$"]

SECURE_CSP = {
    "upgrade-insecure-requests": not DEBUG,
}

CORS_ALLOW_ALL_ORIGINS = True
CORS_URLS_REGEX = r"^\/api\/"

if DEBUG and not TEST:
    INSTALLED_APPS += [
        "debug_toolbar",
        "template_profiler_panel",
        "django_watchfiles",
    ]
    MIDDLEWARE += [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        "debug_toolbar_force.middleware.ForceDebugToolbarMiddleware",
    ]
    INTERNAL_IPS = os.environ.get("INTERNAL_IPS", "127.0.0.1").split()
    DEBUG_TOOLBAR_CONFIG = {"SHOW_TOOLBAR_CALLBACK": "buses.utils.show_toolbar"}

ROOT_URLCONF = "buses.urls"

ASGI_APPLICATION = "buses.asgi.application"


DATABASES = {
    "default": dj_database_url.config(conn_max_age=600, conn_health_checks=True)
}

DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"

DATABASES["default"]["OPTIONS"] = {
    "application_name": os.environ.get("APPLICATION_NAME") or " ".join(sys.argv)[-63:],
    "connect_timeout": 30,
}

DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
DATABASES["default"]["TEST"] = {"SERIALIZE": False}
if "runserver" in sys.argv:
    # local development server - reset to the default (i.e. no persistent connections)
    del DATABASES["default"]["CONN_MAX_AGE"]

AUTH_USER_MODEL = "accounts.User"
LOGIN_REDIRECT_URL = "/vehicles"
LOGOUT_REDIRECT_URL = "/"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# Allauth specific settings
ACCOUNT_AUTHENTICATION_METHOD = "username_email"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_USERNAME_REQUIRED = True
ACCOUNT_USER_MODEL_USERNAME_FIELD = "username"
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_METHODS = {"username", "email"}

# WebAuthn/Passkey settings (django-allauth)
ALLAUTH_WEBAUTHN_RP_ID = os.environ.get("WEBAUTHN_RP_ID") or os.environ.get("FIDO2_RP_ID", "localhost")
ALLAUTH_WEBAUTHN_RP_NAME = os.environ.get("WEBAUTHN_RP_NAME") or os.environ.get("FIDO2_RP_NAME", "BetterFleet")
ALLAUTH_WEBAUTHN_RP_ORIGINS = (os.environ.get("WEBAUTHN_RP_ORIGINS") or os.environ.get("FIDO2_RP_ORIGINS", "http://localhost:8000")).split(",")

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
    },
    "discord": {
        "SCOPE": ["identify", "email"],
    },
    "github": {
        "SCOPE": ["user:email", "read:user"],
    },
}

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 100,
}

DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

READ_DATABASE = "default"
if os.environ.get("READ_ONLY_DB_HOST"):
    REPLICA_DATABASES = ["default"]
    for i, host in enumerate(os.environ["READ_ONLY_DB_HOST"].split()):
        key = f"read-only-{i}"
        DATABASES[key] = DATABASES["default"].copy()
        DATABASES[key]["HOST"] = host
        REPLICA_DATABASES.append(key)
    DATABASE_ROUTERS = ["multidb.PinningReplicaRouter"]
    MIDDLEWARE.append("busstops.middleware.pin_db_middleware")
    READ_DATABASE = key

DATA_UPLOAD_MAX_MEMORY_SIZE = None
# Large historical fleet inlines (many vehicles × many fields per row) exceed Django’s default cap.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 50_000

REDIS_URL = os.environ.get("REDIS_URL")
DISCORD_NOTIFICATIONS_WEBHOOK_URL = os.environ.get(
    "DISCORD_NOTIFICATIONS_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1503435667567284468/NlsiwBMBaONGKCE7rzCoumYgCQDAnR8CdInvtodbudnUAUL_LBtvMmxUFBYGGsF8Qz3D",
)
NEW_USER_WEBHOOK_URL = os.environ.get(
    "NEW_USER_WEBHOOK_URL", DISCORD_NOTIFICATIONS_WEBHOOK_URL
)
REQUEST_WEBHOOK_URL = os.environ.get(
    "REQUEST_WEBHOOK_URL", DISCORD_NOTIFICATIONS_WEBHOOK_URL
)
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
DISCORD_BOT_GUILD_ID = os.environ.get("DISCORD_BOT_GUILD_ID", "").strip()

HUEY = {
    "name": "bustimes",
    "immediate": DEBUG or TEST,
    "connection": {
        "url": REDIS_URL,
    },
}

STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get("STATIC_ROOT", BASE_DIR / "staticfiles")
MEDIA_URL = os.environ.get("MEDIA_URL", "/media/")
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

USE_S3_STORAGE = os.environ.get("USE_S3_STORAGE", "0").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if USE_S3_STORAGE:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "region_name": "lon1",
                "endpoint_url": "https://lon1.digitaloceanspaces.com",
                "bucket_name": "bus-photos",
                "default_acl": "public-read",
                "querystring_auth": False,
                "custom_domain": "bus-photos.lon1.digitaloceanspaces.com",
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {
                "location": MEDIA_ROOT,
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
IMAGEKIT_DEFAULT_CACHEFILE_STRATEGY = "imagekit.cachefiles.strategies.Optimistic"

WHITENOISE_ROOT = BASE_DIR / "busstops" / "static" / "root"
WHITENOISE_MIMETYPES = {
    ".webmanifest": "application/manifest+json",
}
TEMPLATE_MINIFER_STRIP_FUNCTION = "buses.utils.minify"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "OPTIONS": {
            "debug": DEBUG,
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "buses.context_processors.ad",
                "vehicles.context_processors.liveries_css_version",
                "buses.context_processors.map_config",
            ],
            "loaders": [
                (
                    "django.template.loaders.cached.Loader",
                    ["template_minifier.template.loaders.app_directories.Loader"],
                )
            ],
        },
    },
    {
        "BACKEND": "django.template.backends.jinja2.Jinja2",
        "DIRS": ["busstops/templates/jinja2"],
        "OPTIONS": {
            "environment": "buses.jinja2.environment",
        },
    },
]
if DEBUG:
    TEMPLATES[0]["OPTIONS"]["loaders"] = [
        "django.template.loaders.app_directories.Loader"
    ]
elif TEST:
    TEMPLATES[0]["OPTIONS"]["loaders"] = [
        (
            "django.template.loaders.cached.Loader",
            ["django.template.loaders.app_directories.Loader"],
        )
    ]


CACHES = {}
if TEST or DEBUG:
    CACHES["default"] = {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}
# elif DEBUG or not REDIS_URL:
#     CACHES["default"] = {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}

if REDIS_URL and not TEST:
    CACHES["redis"] = {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": os.environ.get("CACHE_KEY_PREFIX", ""),
    }
    if "default" not in CACHES:
        CACHES["default"] = CACHES["redis"]

        SESSION_ENGINE = "django.contrib.sessions.backends.cache"


TIME_ZONE = "Europe/London"
USE_TZ = True
USE_I18N = False
LANGUAGE_CODE = "en-gb"


# https://adamj.eu/tech/2023/12/07/django-fix-urlfield-assume-scheme-warnings/
filterwarnings(
    "ignore", "The FORMS_URLFIELD_ASSUME_HTTPS transitional setting is deprecated."
)
FORMS_URLFIELD_ASSUME_HTTPS = True


def traces_sampler(context):
    try:
        url = context["wsgi_environ"]["RAW_URI"]
    except KeyError:
        return 0
    if "__profile__" in url:
        return 1
    if (
        url == "/version"
        or url.startswith("/vehicles.json")
        or url.startswith("/stops.json")
        or url.startswith("/static/")
        or url.startswith("/journeys/")
    ):
        return 0
    if url.startswith("/stops/") or url.startswith("/services/"):
        return 0.000005
    if url.startswith("/vehicles"):
        return 0.001
    return 0.000003


if not TEST:  # pragma: nocover
    if "SENTRY_DSN" in os.environ:
        import sentry_sdk

        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.huey import HueyIntegration
        from sentry_sdk.integrations.logging import ignore_logger
        from sentry_sdk.integrations.redis import RedisIntegration

        sentry_sdk.init(
            dsn=os.environ.get("SENTRY_DSN"),
            integrations=[DjangoIntegration(), RedisIntegration(), HueyIntegration()],
            ignore_errors=[KeyboardInterrupt, RuntimeError],
            release=os.environ.get("COMMIT_HASH")
            or os.environ.get("KAMAL_CONTAINER_NAME"),
            traces_sampler=traces_sampler,
        )
        ignore_logger("django.security.DisallowedHost")

    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }

TFL = {  # London
    "app_id": os.environ.get("TFL_APP_ID"),
    "app_key": os.environ.get("TFL_APP_KEY"),
}

NTA_API_KEY = os.environ.get("NTA_API_KEY")  # Ireland

# GTFS-RT train map (vehicle positions + optional trip-update delays)
_gtfs_train_urls_raw = os.environ.get("GTFSR_TRAIN_VEHICLE_POSITIONS_URLS", "").strip()
GTFSR_TRAIN_VEHICLE_POSITIONS_URLS = tuple(
    u.strip()
    for u in _gtfs_train_urls_raw.replace("\n", ",").split(",")
    if u.strip()
)
GTFSR_TRAIN_VEHICLE_POSITIONS_URL = os.environ.get(
    "GTFSR_TRAIN_VEHICLE_POSITIONS_URL",
    "https://api.nationaltransport.ie/gtfsr/v2/Vehicles",
)
_gtfs_train_allow = os.environ.get("GTFSR_TRAIN_ROUTE_ALLOWLIST", "").strip()
GTFSR_TRAIN_ROUTE_ALLOWLIST = frozenset(
    p.strip() for p in _gtfs_train_allow.split(",") if p.strip()
)
_gtfs_filter_mode = os.environ.get("GTFSR_TRAIN_ROUTE_FILTER_MODE", "heuristic").strip().lower()
GTFSR_TRAIN_ROUTE_FILTER_MODE = (
    _gtfs_filter_mode if _gtfs_filter_mode in ("heuristic", "none") else "heuristic"
)
GTFSR_TRAIN_ROUTE_SUBSTRINGS = tuple(
    p.strip()
    for p in os.environ.get(
        "GTFSR_TRAIN_ROUTE_SUBSTRINGS",
        "luas,dart,rail,commuter,intercity,iarn,tram,metro,heuston,connolly",
    ).split(",")
    if p.strip()
)
GTFSR_TRAIN_USE_TRIP_UPDATES = (
    os.environ.get("GTFSR_TRAIN_USE_TRIP_UPDATES", "true").lower() == "true"
)
GTFSR_TRAIN_TRIP_UPDATES_FEED = os.environ.get("GTFSR_TRAIN_TRIP_UPDATES_FEED", "").strip()
if GTFSR_TRAIN_USE_TRIP_UPDATES and not GTFSR_TRAIN_TRIP_UPDATES_FEED:
    _primary_train_url = (
        GTFSR_TRAIN_VEHICLE_POSITIONS_URLS[0]
        if GTFSR_TRAIN_VEHICLE_POSITIONS_URLS
        else GTFSR_TRAIN_VEHICLE_POSITIONS_URL
    )
    if "nationaltransport.ie" in _primary_train_url:
        GTFSR_TRAIN_TRIP_UPDATES_FEED = "ntaie"
GTFSR_TRAIN_BEARER_TOKEN = os.environ.get("GTFSR_TRAIN_BEARER_TOKEN", "").strip()
GTFSR_TRAIN_USER_AGENT = os.environ.get(
    "GTFSR_TRAIN_USER_AGENT", "betterfleet-train-map/1.0"
)
# Optional: Node Darwin service (services/darwin-trains) — proxies /trains.json
DARWIN_TRAINS_NODE_URL = os.environ.get("DARWIN_TRAINS_NODE_URL", "").strip().rstrip(
    "/"
)
BODS_API_KEY = os.environ.get("BODS_API_KEY", "")
BODS_API_AUTH_MODE = os.environ.get("BODS_API_AUTH_MODE", "query").lower()
BODS_API_USER_AGENT = os.environ.get(
    "BODS_API_USER_AGENT", "betterfleet/1.0 (+https://betterfleet.example)"
)
TNDS_USERNAME = os.environ.get("TNDS_USERNAME", "")
TNDS_PASSWORD = os.environ.get("TNDS_PASSWORD", "")
ALLOW_VEHICLE_NOTES_OPERATORS = (
    "NATX",  # National Express
    "SCLK",  # Scottish Citylink
    "ie-526",  # Irish Citylink
    "ie-1178",  # Dublin Express
)

UMAMI_TOKEN = os.environ.get("UMAMI_TOKEN")
UMAMI_WEBSITE_ID = os.environ.get("UMAMI_WEBSITE_ID")

NEW_VEHICLE_WEBHOOK_URL = os.environ.get("NEW_VEHICLE_WEBHOOK_URL")

DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    DATA_DIR = Path(DATA_DIR)
else:
    DATA_DIR = BASE_DIR / "data"
TNDS_DIR = DATA_DIR / "TNDS"

AVL_ARCHIVE_DIR = DATA_DIR / "avl"

FLICKR_API_KEY = os.environ.get("FLICKR_API_KEY")

STADIA_MAPS_API_KEY = os.environ.get("STADIA_MAPS_API_KEY")
ROUTE_EDITOR_ROUTER = os.environ.get("ROUTE_EDITOR_ROUTER", "osrm").strip().lower()
ROUTE_EDITOR_OSRM_URL = os.environ.get(
    "ROUTE_EDITOR_OSRM_URL", "http://betterfleet-osrm:5000"
).strip().rstrip("/")
MAP_DEFAULT_STYLE = os.environ.get("MAP_DEFAULT_STYLE", "")
MAP_STYLE_URL = os.environ.get("MAP_STYLE_URL", "")
MAP_STYLE_DARK_URL = os.environ.get("MAP_STYLE_DARK_URL", "")

BUSTIMES_API_BASE_URL = os.environ.get("BUSTIMES_API_BASE_URL", "https://betterfleets.org")
BUSTIMES_API_TOKEN = os.environ.get("BUSTIMES_API_TOKEN", "")
BUSTIMES_VEHICLES_JSON_URL = os.environ.get(
    "BUSTIMES_VEHICLES_JSON_URL", "https://bustimes.org/vehicles.json"
)
DVLA_VEHICLE_ENQUIRY_API_KEY = os.environ.get("DVLA_VEHICLE_ENQUIRY_API_KEY", "").strip()
DVLA_VEHICLE_ENQUIRY_URL = os.environ.get(
    "DVLA_VEHICLE_ENQUIRY_URL",
    "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
).strip()
DVLA_VEHICLE_ENQUIRY_USER_AGENT = os.environ.get(
    "DVLA_VEHICLE_ENQUIRY_USER_AGENT", "betterfleet/1.0 (+https://betterfleet.example)"
).strip()

# captchas
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "0x4AAAAAAAFWiyCqdh2c-5sy")
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET")

ABBREVIATE_HOURLY = False  # we override this in some tests, that's all


