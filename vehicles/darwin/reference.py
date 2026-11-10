"""Darwin reference data - TIPLOC names/CRS codes and TOC names,
from the daily *_ref_v*.xml.gz files on the timetable S3 bucket.
"""

import gzip
import hashlib
import hmac
import logging
import os
import re
from datetime import UTC, datetime
from xml.etree import ElementTree

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

BUCKET = "darwin.xmltimetable"
PREFIX = "PPTimetable/"
REGION = "eu-west-1"
CACHE_KEY = "darwin_reference_data"
CACHE_SECONDS = 60 * 60 * 12

NS = "{http://www.thalesgroup.com/rtti/XmlRefData/v4}"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _s3_get(key: str) -> bytes:
    """SigV4-signed GET for the Darwin timetable bucket (no boto3 dependency)"""
    access_key = os.environ["DARWIN_S3_ACCESS_KEY"]
    secret_key = os.environ["DARWIN_S3_SECRET_KEY"]

    host = f"{BUCKET}.s3.{REGION}.amazonaws.com"
    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    canonical_uri = f"/{key}"  # key already includes the PPTimetable/ prefix
    canonical_request = "\n".join(
        [
            "GET",
            canonical_uri,
            "",
            f"host:{host}\nx-amz-date:{amz_date}\n",
            "host;x-amz-date",
            "UNSIGNED-PAYLOAD",
        ]
    )
    scope = f"{date_stamp}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signing_key = _sign(
        _sign(
            _sign(_sign(f"AWS4{secret_key}".encode(), date_stamp), REGION), "s3"
        ),
        "aws4_request",
    )
    signature = hmac.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    url = f"https://{host}{canonical_uri}"
    response = requests.get(
        url,
        headers={
            "x-amz-date": amz_date,
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                f"SignedHeaders=host;x-amz-date, Signature={signature}"
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def list_bucket_xml() -> str:
    """SigV4-signed GET on the bucket root with list-type=2"""
    access_key = os.environ["DARWIN_S3_ACCESS_KEY"]
    secret_key = os.environ["DARWIN_S3_SECRET_KEY"]

    host = f"{BUCKET}.s3.{REGION}.amazonaws.com"
    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    # canonical query params must be sorted by name and URI-encoded
    query = "list-type=2&max-keys=1000&prefix=PPTimetable%2F"
    canonical_request = "\n".join(
        [
            "GET",
            "/",
            query,
            f"host:{host}\nx-amz-date:{amz_date}\n",
            "host;x-amz-date",
            "UNSIGNED-PAYLOAD",
        ]
    )
    scope = f"{date_stamp}/{REGION}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signing_key = _sign(
        _sign(
            _sign(_sign(f"AWS4{secret_key}".encode(), date_stamp), REGION), "s3"
        ),
        "aws4_request",
    )
    signature = hmac.new(
        signing_key, string_to_sign.encode(), hashlib.sha256
    ).hexdigest()

    response = requests.get(
        f"https://{host}/?{query}",  # already canonical-encoded
        headers={
            "x-amz-date": amz_date,
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
                f"SignedHeaders=host;x-amz-date, Signature={signature}"
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.text


def get_latest_ref_key() -> str:
    xml = list_bucket_xml()
    keys = re.findall(r"<Key>([^<]+_ref_v4\.xml\.gz)</Key>", xml)
    if not keys:
        # fall back to any ref version
        keys = re.findall(r"<Key>([^<]+_ref_v\d+\.xml\.gz)</Key>", xml)
    if not keys:
        raise RuntimeError("no Darwin reference data files found")
    return sorted(keys)[-1]


def parse_reference(xml_text: str) -> dict:
    """returns {
        "locations": {tpl: {"locname", "crs", "toc"}},
        "tocs": {toc: tocname},
    }"""
    root = ElementTree.fromstring(xml_text)

    locations = {}
    for loc in root.iter(f"{NS}LocationRef"):
        locations[loc.get("tpl")] = {
            "locname": loc.get("locname") or loc.get("tpl"),
            "crs": loc.get("crs"),
            "toc": loc.get("toc"),
        }

    tocs = {
        toc.get("toc"): (toc.get("tocname") or "").replace("&amp;", "&")
        for toc in root.iter(f"{NS}TocRef")
    }

    return {"locations": locations, "tocs": tocs}


def get_reference_data(force=False) -> dict | None:
    if not force and (cached := cache.get(CACHE_KEY)):
        return cached

    try:
        key = get_latest_ref_key()
        data = _s3_get(key)
        reference = parse_reference(gzip.decompress(data).decode("utf-8"))
    except Exception:
        logger.exception("error fetching Darwin reference data")
        return cache.get(CACHE_KEY) or None

    cache.set(CACHE_KEY, reference, CACHE_SECONDS)
    return reference
