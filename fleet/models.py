from django.conf import settings
from django.db import models
from django.utils.crypto import constant_time_compare
import hashlib
import uuid
from busstops.models import Operator


class FleetPDFUpload(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    file = models.FileField(upload_to="fleet-pdfs/")
    original_filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def __str__(self):
        return self.original_filename or self.file.name or f"PDF upload {self.pk}"

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = self.file.name.rsplit("/", 1)[-1]
        super().save(*args, **kwargs)


class FleetVehicle(models.Model):
    operator_code = models.CharField(max_length=32, default="EXLS", db_index=True)
    external_id = models.CharField(max_length=100, blank=True)
    code = models.CharField(max_length=64, blank=True)
    fleet_number = models.CharField(max_length=32, blank=True, db_index=True)
    fleet_code = models.CharField(max_length=32, blank=True, db_index=True)
    registration = models.CharField(max_length=24, blank=True, db_index=True)
    prev_registration = models.CharField(max_length=255, blank=True)
    vehicle_type = models.CharField(max_length=255, blank=True, db_index=True)
    livery = models.CharField(max_length=255, blank=True, db_index=True)
    colours = models.CharField(max_length=255, blank=True)
    garage = models.CharField(max_length=255, blank=True, db_index=True)
    name = models.CharField(max_length=255, blank=True)
    branding = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    withdrawn = models.BooleanField(default=False)
    preserved = models.BooleanField(default=False)
    fleet_support_vehicle = models.BooleanField(default=False)
    vor = models.BooleanField(default=False)
    awaiting_delivery = models.BooleanField(default=False)
    trainer_vehicle = models.BooleanField(default=False)
    demonstrator = models.BooleanField(default=False)
    source_pdf = models.ForeignKey(
        FleetPDFUpload,
        on_delete=models.CASCADE,
        related_name="vehicles",
    )
    source_page = models.PositiveIntegerField(default=1)
    raw_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("source_pdf", "source_page", "fleet_number", "fleet_code", "code")

    def __str__(self):
        return self.fleet_code or self.fleet_number or self.registration or self.code

    def operator_match(self):
        from fleet.matching import match_operator_for_row

        return match_operator_for_row(self)

    def garage_match(self):
        from fleet.matching import match_garage_for_row

        return match_garage_for_row(self)


class FleetRideLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,
        related_name="fleet_ride_logs",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.CASCADE,
        related_name="ride_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "vehicle"),
                name="fleet_unique_user_vehicle_ride_log",
            )
        ]
        permissions = [
            ("use_beta_features", "Beta Features"),
        ]
        verbose_name = "fleet ride log"
        verbose_name_plural = "fleet ride logs"

    def __str__(self):
        return f"{self.user} rode {self.vehicle}"


class FleetDrivingLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,
        related_name="fleet_driving_logs",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.CASCADE,
        related_name="driving_logs",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Optional notes about this driving experience")

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "vehicle"),
                name="fleet_unique_user_vehicle_driving_log",
            )
        ]
        verbose_name = "fleet driving log"
        verbose_name_plural = "fleet driving logs"

    def __str__(self):
        return f"{self.user} drove {self.vehicle}"


class FleetPhotoLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,
        related_name="fleet_photo_logs",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.CASCADE,
        related_name="photo_logs",
    )
    quantity = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Optional notes about this photograph")

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "vehicle"),
                name="fleet_unique_user_vehicle_photo_log",
            )
        ]
        verbose_name = "fleet photo log"
        verbose_name_plural = "fleet photo logs"

    def __str__(self):
        return f"{self.user} photographed {self.vehicle}"


class OverlandSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,
        related_name="overland_subscriptions",
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.CASCADE,
        related_name="overland_subscriptions",
    )
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    destination = models.CharField(max_length=255, blank=True)
    route_number = models.CharField(max_length=64, blank=True)
    trip_id = models.CharField(max_length=128, blank=True)
    scheduled_trip = models.ForeignKey(
        "bustimes.Trip",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="overland_subscriptions",
    )
    tracking_date = models.DateField(null=True, blank=True)
    journey = models.ForeignKey(
        "vehicles.VehicleJourney",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="overland_subscriptions",
    )
    auth_key_hash = models.CharField(max_length=64)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    heading = models.IntegerField(null=True, blank=True)
    last_timestamp = models.DateTimeField(null=True, blank=True)
    capacity_current = models.PositiveIntegerField(default=0, null=True, blank=True)
    capacity_max = models.PositiveIntegerField(default=0, null=True, blank=True)
    capacity_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-updated_at",)
        permissions = [
            ("use_overland", "Can generate Overland tracking URLs"),
        ]

    @staticmethod
    def hash_auth_key(auth_key):
        return hashlib.sha256(auth_key.encode()).hexdigest()

    def check_auth_key(self, auth_key):
        return constant_time_compare(self.auth_key_hash, self.hash_auth_key(auth_key))

    def __str__(self):
        return f"{self.vehicle} Overland tracking"


class PinnedOperator(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,
        related_name="pinned_operators",
    )
    operator = models.ForeignKey(
        Operator,
        models.CASCADE,
        related_name="pinned_by_users",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "operator"),
                name="fleet_unique_user_pinned_operator",
            )
        ]
        verbose_name = "pinned operator"
        verbose_name_plural = "pinned operators"

    def __str__(self):
        return f"{self.user} pinned {self.operator}"
