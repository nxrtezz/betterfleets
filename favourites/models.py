from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

User = get_user_model()

MAX_FAVOURITES = 15


class FavouriteType(models.TextChoices):
    OPERATOR = "operator", "Operator"
    VEHICLE = "vehicle", "Vehicle"
    SERVICE = "service", "Service"


class Favourite(models.Model):
    """
    User favourites for operators, vehicles, and services.
    
    Maximum 15 favourites per user per type. Enforces unique constraints
    and validates that exactly one foreign key is set based on favourite type.
    """
    user = models.ForeignKey(User, models.CASCADE, related_name="favourites")
    favourite_type = models.CharField(
        max_length=20,
        choices=FavouriteType.choices
    )
    operator = models.ForeignKey(
        "busstops.Operator",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="favourited_by"
    )
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="favourited_by"
    )
    service = models.ForeignKey(
        "busstops.Service",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="favourited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="Optional notes about this favourite")
    
    class Meta:
        ordering = ("-created_at",)
        verbose_name = "favourite"
        verbose_name_plural = "favourites"
        unique_together = ("user", "favourite_type", "operator", "vehicle", "service")
        indexes = [
            models.Index(fields=["user", "favourite_type"]),
            models.Index(fields=["favourite_type", "created_at"]),
        ]
    
    def __str__(self):
        if self.favourite_type == FavouriteType.OPERATOR:
            return f"{self.user} - {self.operator}"
        elif self.favourite_type == FavouriteType.VEHICLE:
            return f"{self.user} - {self.vehicle}"
        elif self.favourite_type == FavouriteType.SERVICE:
            return f"{self.user} - {self.service}"
        return f"{self.user} - {self.favourite_type}"
    
    def clean(self):
        # Validate that exactly one foreign key is set based on type
        if self.favourite_type == FavouriteType.OPERATOR:
            if not self.operator:
                raise ValidationError("Operator must be set for operator favourites.")
            if self.vehicle or self.service:
                raise ValidationError("Only operator should be set for operator favourites.")
        elif self.favourite_type == FavouriteType.VEHICLE:
            if not self.vehicle:
                raise ValidationError("Vehicle must be set for vehicle favourites.")
            if self.operator or self.service:
                raise ValidationError("Only vehicle should be set for vehicle favourites.")
        elif self.favourite_type == FavouriteType.SERVICE:
            if not self.service:
                raise ValidationError("Service must be set for service favourites.")
            if self.operator or self.vehicle:
                raise ValidationError("Only service should be set for service favourites.")
        
        # Check max favourites per type
        if self.pk:
            # Updating existing favourite, don't count it
            count = Favourite.objects.filter(
                user=self.user,
                favourite_type=self.favourite_type
            ).exclude(pk=self.pk).count()
        else:
            # New favourite
            count = Favourite.objects.filter(
                user=self.user,
                favourite_type=self.favourite_type
            ).count()
        
        if count >= MAX_FAVOURITES:
            raise ValidationError(
                f"Maximum {MAX_FAVOURITES} favourites allowed per type. "
                f"You currently have {count} {self.get_favourite_type_display().lower()} favourites."
            )
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
