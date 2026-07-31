from django.conf import settings
from django.db import models
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


class LiveVehicleLocation(models.Model):
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.CASCADE,
        related_name="live_locations",
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    headcode = models.CharField(max_length=16, blank=True)
    destination = models.CharField(max_length=255, blank=True)
    rotation = models.IntegerField(null=True, blank=True, help_text="Vehicle heading in degrees (0-360)")
    lateness = models.IntegerField(null=True, blank=True, help_text="Lateness in minutes (negative for early)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "live vehicle location"
        verbose_name_plural = "live vehicle locations"

    def __str__(self):
        return f"{self.vehicle} at {self.latitude}, {self.longitude}"


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


class ManualTrackingSimulation(models.Model):
    """
    Simulation routes for manual tracking using snap-to-road routing.
    
    Allows users to create simulated vehicle movements along routes
    using OSRM routing with speed limits, either by selecting bus stops
    or by selecting operator/service/direction.
    """
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.CASCADE,
        related_name="manual_simulations",
        help_text='The vehicle to simulate tracking for'
    )
    name = models.CharField(
        max_length=255,
        help_text='Name for this simulation route'
    )
    route_type = models.CharField(
        max_length=20,
        choices=[
            ('stops', 'Selected Bus Stops'),
            ('service', 'Service Route'),
        ],
        default='stops',
        help_text='How the route is defined'
    )
    
    # For service-based routes
    service = models.ForeignKey(
        "busstops.Service",
        models.CASCADE,
        null=True,
        blank=True,
        related_name='manual_simulations',
        help_text='Service for service-based routes'
    )
    direction = models.CharField(
        max_length=10,
        choices=[
            ('inbound', 'Inbound'),
            ('outbound', 'Outbound'),
        ],
        blank=True,
        help_text='Direction for service-based routes'
    )
    
    # For stop-based routes
    stops = models.JSONField(
        default=list,
        blank=True,
        help_text='Ordered list of stop coordinates [{"lat": 51.5, "lng": -0.1, "stop_id": 123}, ...]'
    )
    
    # Route geometry and timing
    route_geometry = models.JSONField(
        null=True,
        blank=True,
        help_text='OSRM route geometry as GeoJSON LineString'
    )
    route_segments = models.JSONField(
        default=list,
        blank=True,
        help_text='Route segments with speed limits and timing data'
    )
    
    # Simulation state
    is_active = models.BooleanField(
        default=False,
        help_text='Whether the simulation is currently running'
    )
    current_position = models.JSONField(
        null=True,
        blank=True,
        help_text='Current vehicle position {"lat": 51.5, "lng": -0.1, "heading": 90}'
    )
    started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the simulation started'
    )
    progress = models.FloatField(
        default=0,
        help_text='Progress along route (0.0 to 1.0)'
    )
    
    # Speed multiplier (1.0 = real speed, 2.0 = 2x speed, etc.)
    speed_multiplier = models.FloatField(
        default=1.0,
        help_text='Speed multiplier for simulation (1.0 = normal speed)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,
        related_name='manual_simulations',
        help_text='User who created this simulation'
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=['vehicle']),
            models.Index(fields=['is_active']),
            models.Index(fields=['service']),
        ]
        verbose_name = "manual tracking simulation"
        verbose_name_plural = "manual tracking simulations"

    def __str__(self):
        return f"{self.name} ({self.vehicle})"
