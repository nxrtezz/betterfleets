from django.db import models
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

User = get_user_model()


class RequestCategory(models.TextChoices):
    VEHICLE = "vehicle", "Vehicle"
    SERVICE = "service", "Service"
    OPERATOR = "operator", "Operator"
    VEHICLE_TYPE = "vehicle_type", "Vehicle Type"
    LIVERY = "livery", "Livery"
    SITE_FEATURE = "site_feature", "Site Feature"
    NAMED_PAGE = "named_page", "Named Page"
    PHOTO = "photo", "Photo"
    OTHER = "other", "Other"


class RequestStatus(models.TextChoices):
    OPEN = "open", "Open"
    IN_PROGRESS = "in_progress", "In Progress"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"
    DECLINED = "declined", "Declined"


class Request(models.Model):
    """
    Main request model for user-submitted improvements to BetterFleets.
    Supports multiple categories with category-specific fields.
    """
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(
        max_length=20,
        choices=RequestCategory.choices,
        default=RequestCategory.OTHER
    )
    status = models.CharField(
        max_length=20,
        choices=RequestStatus.choices,
        default=RequestStatus.OPEN
    )
    author = models.ForeignKey(User, models.CASCADE, related_name="requests")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Category-specific fields (nullable, used based on category)
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests"
    )
    service = models.ForeignKey(
        "busstops.Service",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests"
    )
    operator = models.ForeignKey(
        "busstops.Operator",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests"
    )
    vehicle_type = models.ForeignKey(
        "vehicles.VehicleType",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests"
    )
    livery = models.ForeignKey(
        "vehicles.Livery",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="requests"
    )
    
    # Additional fields for specific request types
    fleet_number = models.CharField(max_length=50, blank=True)
    registration = models.CharField(max_length=24, blank=True)
    route = models.CharField(max_length=100, blank=True)
    expected_behaviour = models.TextField(blank=True)
    photo_url = models.URLField(blank=True, help_text="Flickr photo URL for photo requests")
    
    # Tracking
    resolved_by = models.ForeignKey(
        User,
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_requests"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    history = HistoricalRecords(
        inherit=True,
        related_name="request_history"
    )
    
    class Meta:
        ordering = ("-created_at",)
        verbose_name = "request"
        verbose_name_plural = "requests"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["category"]),
            models.Index(fields=["created_at"]),
        ]
    
    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
    
    def get_absolute_url(self):
        return reverse("service_requests:detail", args=(self.id,))
    
    def save(self, *args, **kwargs):
        # Auto-update resolved_at when status changes to resolved
        if self.status == RequestStatus.RESOLVED and not self.resolved_at:
            self.resolved_at = timezone.now()
        elif self.status != RequestStatus.RESOLVED:
            self.resolved_at = None
        super().save(*args, **kwargs)


class RequestComment(models.Model):
    """Comments on requests for discussion and updates."""
    request = models.ForeignKey(Request, models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, models.CASCADE, related_name="request_comments")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ("created_at",)
        verbose_name = "request comment"
        verbose_name_plural = "request comments"
    
    def __str__(self):
        return f"Comment by {self.author} on {self.request}"


class RequestHistory(models.Model):
    """Timeline/history of changes to requests."""
    request = models.ForeignKey(Request, models.CASCADE, related_name="timeline")
    user = models.ForeignKey(User, models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Optional link to affected object
    related_object_type = models.CharField(max_length=50, blank=True)
    related_object_id = models.IntegerField(null=True, blank=True)
    
    class Meta:
        ordering = ("-created_at",)
        verbose_name = "request history"
        verbose_name_plural = "request history"
    
    def __str__(self):
        return f"{self.action} on {self.request}"
