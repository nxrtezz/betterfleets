from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError


def validate_flickr_url(value):
    """Validate that the URL is from Flickr."""
    if not value:
        return
    if "flickr.com" not in value.lower():
        raise ValidationError("Only Flickr URLs are allowed for photos.")


class Photo(models.Model):
    flickr_url = models.URLField(
        validators=[validate_flickr_url],
        verbose_name="Flickr URL",
        help_text="Enter a Flickr photo URL"
    )
    credit = models.CharField(max_length=255, blank=True)
    caption = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    license = models.CharField(null=True, blank=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True
    )

    vehicles = models.ManyToManyField("vehicles.Vehicle", blank=True)

    livery = models.ForeignKey(
        "vehicles.Livery", models.SET_NULL, null=True, blank=True
    )
    vehicle_type = models.ForeignKey(
        "vehicles.VehicleType", models.SET_NULL, null=True, blank=True
    )
    service = models.ForeignKey(
        "busstops.Service", models.SET_NULL, null=True, blank=True
    )

    def get_display_url(self):
        """Return the Flickr URL for displaying this photo."""
        return self.flickr_url

    def __str__(self):
        return self.caption or self.flickr_url
