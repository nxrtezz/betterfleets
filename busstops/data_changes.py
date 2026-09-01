from __future__ import annotations

import datetime
import hashlib
import re
from decimal import Decimal
from typing import Any

import requests
from django.apps import apps
from django.contrib.gis.geos import GEOSGeometry
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import DataChangeLog
from photos.models import Photo


def _get_flickr_image_info(flickr_url):
    """Extract the actual image URL and optional credit from a Flickr photo page."""
    try:
        response = requests.get(flickr_url, timeout=10)
        response.raise_for_status()
        
        # Use regex to find the image URL and alt text in the noscript tag
        # Pattern to match: <img src="..." alt="...">
        pattern = r'<img[^>]*src=["\']([^"\']*staticflickr[^"\']*)["\'][^>]*alt=["\']([^"\']*)["\']'
        matches = re.findall(pattern, response.text)
        
        if matches:
            image_url, alt_text = matches[0]
            # Ensure it has the protocol
            if image_url.startswith('//'):
                image_url = 'https:' + image_url
            
            # Extract credit from alt text (format: "... | by author")
            credit = ""
            if alt_text and '| by' in alt_text:
                credit = alt_text.split('| by')[-1].strip()
            elif alt_text:
                # Fallback: use the entire alt text if no "| by" pattern
                credit = alt_text.strip()
            
            return image_url, credit
        
        return None, None
    except Exception as e:
        print(f"Error extracting Flickr image info: {e}")
        return None, None


def target_model_label(instance: Any) -> str:
    return instance._meta.label_lower


def target_pk(instance: Any) -> str:
    return str(instance.pk or "")


def target_repr(instance: Any) -> str:
    return str(instance)[:255] if instance.pk else ""


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, GEOSGeometry):
        return value.wkt
    if hasattr(value, "wkt"):
        return value.wkt
    if hasattr(value, "pk"):
        return str(value.pk) if value.pk is not None else None
    return value


def record_applied_change(
    *,
    source: str,
    instance: Any,
    operation: str,
    changes: dict[str, dict[str, Any]],
    payload: dict[str, Any] | None = None,
) -> DataChangeLog:
    return DataChangeLog.objects.create(
        source=source,
        target_model=target_model_label(instance),
        target_pk=target_pk(instance),
        target_repr=target_repr(instance),
        operation=operation,
        changes=_json_safe_value(changes),
        payload=_json_safe_value(payload or {}),
        status=DataChangeLog.STATUS_APPLIED,
        applied_at=timezone.now(),
    )


def record_pending_change(
    *,
    source: str,
    instance: Any,
    operation: str,
    changes: dict[str, dict[str, Any]],
    payload: dict[str, Any] | None = None,
    reason: str = "",
) -> DataChangeLog:
    existing = (
        DataChangeLog.objects.filter(
            source=source,
            target_model=target_model_label(instance),
            target_pk=target_pk(instance),
            operation=operation,
            status=DataChangeLog.STATUS_PENDING,
        )
        .order_by("-created_at")
        .first()
    )
    if existing:
        existing.changes = {
            **(existing.changes or {}),
            **_json_safe_value(changes),
        }
        existing.payload = _json_safe_value(payload or existing.payload or {})
        existing.reason = reason or existing.reason
        existing.target_repr = target_repr(instance)
        existing.save(update_fields=["changes", "payload", "reason", "target_repr"])
        return existing

    return DataChangeLog.objects.create(
        source=source,
        target_model=target_model_label(instance),
        target_pk=target_pk(instance),
        target_repr=target_repr(instance),
        operation=operation,
        changes=_json_safe_value(changes),
        payload=_json_safe_value(payload or {}),
        status=DataChangeLog.STATUS_PENDING,
        reason=reason,
    )


def _coerce_field_value(instance: Any, field_name: str, value: Any) -> tuple[str, Any]:
    model_field = instance._meta.get_field(field_name)
    if getattr(model_field, "is_relation", False):
        return model_field.attname, value or None
    if getattr(model_field, "geom_type", None) and isinstance(value, str):
        return field_name, GEOSGeometry(value)
    return field_name, value


@transaction.atomic
def apply_pending_change(log: DataChangeLog, *, user=None) -> DataChangeLog:
    if log.status != DataChangeLog.STATUS_PENDING:
        return log

    # Handle photo suggestions specially
    if log.operation == "add_photo" and log.source == "photo_suggestion":
        model = apps.get_model(log.target_model)
        instance = model._default_manager.select_for_update().get(pk=log.target_pk)
        flickr_url = (log.payload or {}).get("flickr_url")
        
        if flickr_url:
            try:
                # Extract image URL and optional credit from Flickr page
                image_url, credit = _get_flickr_image_info(flickr_url)
                
                if not image_url:
                    log.reason = "Could not extract image URL from Flickr page"
                    log.status = DataChangeLog.STATUS_REJECTED
                    log.save(update_fields=["status", "reason"])
                    return log
                
                # Download the image
                image_response = requests.get(image_url, timeout=10)
                image_response.raise_for_status()
                
                with transaction.atomic():
                    # Create the photo
                    photo = Photo()
                    photo.user = user
                    photo.credit = credit or ""

                    # Save the image first to prevent automatic Flickr download
                    sha1 = hashlib.sha1(usedforsecurity=False)
                    sha1.update(image_response.content)
                    photo.image.save(
                        f"{sha1.hexdigest()}.jpg",
                        ContentFile(image_response.content),
                    )

                    # Now set the flickr_url after image is saved to prevent automatic download
                    photo.flickr_url = flickr_url

                    photo.save()
                    photo.vehicles.add(instance)
            except Exception as e:
                # Log the error but don't fail the entire transaction
                log.reason = f"Failed to download photo: {str(e)}"
                log.status = DataChangeLog.STATUS_REJECTED
                log.save(update_fields=["status", "reason"])
                return log
        
        log.status = DataChangeLog.STATUS_APPLIED
        log.approved_by = user
        log.applied_at = timezone.now()
        log.save(update_fields=["status", "approved_by", "applied_at"])
        return log

    model = apps.get_model(log.target_model)
    if log.operation == "create":
        instance = model()
        field_values = dict((log.payload or {}).get("fields") or {})
        if not field_values:
            field_values = {
                field_name: change.get("to")
                for field_name, change in (log.changes or {}).items()
            }
        many_to_many = dict((log.payload or {}).get("many_to_many") or {})

        for field_name, value in field_values.items():
            attr_name, coerced = _coerce_field_value(instance, field_name, value)
            setattr(instance, attr_name, coerced)

        instance.save()

        for field_name, values in many_to_many.items():
            getattr(instance, field_name).set(values or [])
    else:
        instance = model._default_manager.select_for_update().get(pk=log.target_pk)
        many_to_many = dict((log.payload or {}).get("many_to_many") or {})
        update_fields: list[str] = []
        for field_name, change in (log.changes or {}).items():
            if field_name in many_to_many:
                continue
            attr_name, value = _coerce_field_value(instance, field_name, change.get("to"))
            setattr(instance, attr_name, value)
            update_fields.append(attr_name)

        if update_fields:
            instance.save(update_fields=sorted(set(update_fields)))

        for field_name, values in many_to_many.items():
            getattr(instance, field_name).set(values or [])

    log.status = DataChangeLog.STATUS_APPLIED
    log.approved_by = user
    log.applied_at = timezone.now()
    log.target_pk = target_pk(instance)
    log.target_repr = target_repr(instance)
    log.save(
        update_fields=["status", "approved_by", "applied_at", "target_pk", "target_repr"]
    )
    return log


@transaction.atomic
def reject_pending_change(
    log: DataChangeLog, *, user=None, reason: str = ""
) -> DataChangeLog:
    if log.status != DataChangeLog.STATUS_PENDING:
        return log
    log.status = DataChangeLog.STATUS_REJECTED
    log.approved_by = user
    log.reason = reason or log.reason
    log.save(update_fields=["status", "approved_by", "reason"])
    return log
