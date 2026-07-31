from django.db import models
from django.db.models import Index
from django.conf import settings


class EventType(models.TextChoices):
    TRANSFER = "transfer", "Transfer"
    REPAINT = "repaint", "Repaint"
    RENUMBERED = "renumbered", "Renumbered"
    REGISTRATION_CHANGE = "registration_change", "Registration Change"
    NAME_APPLIED = "name_applied", "Name Applied"
    NAME_REMOVED = "name_removed", "Name Removed"
    BRANDING_APPLIED = "branding_applied", "Branding Applied"
    BRANDING_REMOVED = "branding_removed", "Branding Removed"
    GARAGE_TRANSFER = "garage_transfer", "Garage Transfer"
    ENTERED_SERVICE = "entered_service", "Entered Service"
    WITHDRAWN = "withdrawn", "Withdrawn"
    REINSTATED = "reinstated", "Reinstated"
    PRESERVED = "preserved", "Preserved"
    SCRAPPED = "scrapped", "Scrapped"
    SOLD = "sold", "Sold"
    DELIVERED = "delivered", "Delivered"
    FEATURE_ADDED = "feature_added", "Feature Added"
    FEATURE_REMOVED = "feature_removed", "Feature Removed"
    VOR = "vor", "Vehicle Off Road"
    RETURNED_TO_SERVICE = "returned_to_service", "Returned to Service"
    OTHER = "other", "Other"


class DatePrecision(models.TextChoices):
    DAY = "day", "Day"
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    UNKNOWN = "unknown", "Unknown"


class VehicleHistoryEvent(models.Model):
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
        related_name="history_events",
    )
    event_type = models.CharField(
        max_length=50,
        choices=EventType.choices,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    event_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
    )
    date_precision = models.CharField(
        max_length=20,
        choices=DatePrecision.choices,
        default=DatePrecision.DAY,
    )
    is_future_event = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Mark if this event is planned for the future",
    )
    is_automatic = models.BooleanField(
        default=False,
        help_text="Automatically generated from vehicle changes",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_history_events",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date", "-created_at"]
        indexes = [
            Index(fields=["vehicle"]),
            Index(fields=["event_type"]),
            Index(fields=["event_date"]),
            Index(fields=["is_future_event"]),
            Index(fields=["created_at"]),
            Index(fields=["vehicle", "event_date"]),
            Index(fields=["vehicle", "event_type"]),
        ]
        verbose_name = "Vehicle History Event"
        verbose_name_plural = "Vehicle History Events"

    def __str__(self):
        return f"{self.vehicle} - {self.title}"


class VehicleHistoryAttachment(models.Model):
    event = models.ForeignKey(
        VehicleHistoryEvent,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    photo = models.ForeignKey(
        "photos.Photo",
        on_delete=models.CASCADE,
        related_name="history_attachments",
    )
    caption = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        verbose_name = "Vehicle History Attachment"
        verbose_name_plural = "Vehicle History Attachments"

    def __str__(self):
        return f"{self.event} - {self.caption or 'Attachment'}"
