from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill
import requests
from io import BytesIO
from PIL import Image
import re


def validate_flickr_url(value):
    """Validate that the URL is from Flickr."""
    if value and "flickr.com" not in value.lower():
        raise ValidationError("Only Flickr URLs are allowed for photos.")


def download_image_from_flickr(flickr_url):
    """Download the main image from a Flickr URL."""
    try:
        # Extract photo ID from Flickr URL
        # Flickr URLs typically look like: https://www.flickr.com/photos/username/1234567890/
        import re
        match = re.search(r'/photos/[^/]+/(\d+)/?', flickr_url)
        if not match:
            raise ValidationError("Could not extract photo ID from Flickr URL")
        
        photo_id = match.group(1)
        
        # Try to get the largest available image size
        # Flickr uses different URL patterns for different sizes
        # We'll try common patterns
        possible_sizes = [
            f'https://live.staticflickr.com/{photo_id[:3]}/{photo_id}_{photo_id}_o.jpg',  # Original
            f'https://live.staticflickr.com/{photo_id[:3]}/{photo_id}_{photo_id}_b.jpg',  # Large
            f'https://live.staticflickr.com/{photo_id[:3]}/{photo_id}_{photo_id}_c.jpg',  # Medium
            f'https://live.staticflickr.com/{photo_id[:3]}/{photo_id}_{photo_id}.jpg',     # Default
        ]
        
        last_error = None
        for url in possible_sizes:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200 and response.headers.get('content-type', '').startswith('image/'):
                    return Image.open(BytesIO(response.content))
            except Exception as e:
                last_error = e
                continue
        
        # If all direct URL attempts fail, try the original URL
        response = requests.get(flickr_url, timeout=10)
        response.raise_for_status()
        
        if response.headers.get('content-type', '').startswith('image/'):
            return Image.open(BytesIO(response.content))
        
        raise ValidationError(f"Could not download image from Flickr URL. Last error: {str(last_error)}")
        
    except Exception as e:
        raise ValidationError(f"Could not download image from Flickr URL: {str(e)}")


class Photo(models.Model):
    image = models.ImageField()
    image_1200_630 = ImageSpecField(
        source="image",
        processors=[ResizeToFill(1200, 630)],
        format="JPEG",
        options={"quality": 60},
    )
    flickr_url = models.URLField(
        blank=True,
        null=True,
        verbose_name="Flickr URL",
        help_text="Enter a Flickr photo URL to download the image"
    )
    credit = models.CharField(max_length=255, blank=True)
    caption = models.CharField(max_length=255, blank=True)
    url = models.URLField(blank=True, verbose_name="URL")
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
        """Return the URL to use for displaying this photo."""
        if self.url:
            return self.url
        if self.image:
            return self.image_1200_630.url
        return None

    def download_from_flickr(self):
        """Download image from Flickr URL and save to image field."""
        if self.flickr_url:
            img = download_image_from_flickr(self.flickr_url)
            
            # Convert to RGB if necessary for JPEG
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Save to BytesIO
            output = BytesIO()
            img.save(output, format='JPEG', quality=85)
            output.seek(0)
            
            # Save to image field
            from django.core.files.uploadedfile import SimpleUploadedFile
            import uuid
            filename = f'flickr_{uuid.uuid4().hex[:8]}.jpg'
            self.image.save(
                filename,
                SimpleUploadedFile(
                    filename,
                    output.read(),
                    content_type='image/jpeg'
                ),
                save=False
            )

    def save(self, *args, **kwargs):
        # Download from Flickr if URL is provided and no image exists
        should_download = self.flickr_url and not self.image
        super().save(*args, **kwargs)
        if should_download:
            self.download_from_flickr()
            super().save(update_fields=['image'])

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.flickr_url and "flickr.com" not in self.flickr_url.lower():
            raise ValidationError("Only Flickr URLs are allowed for photos.")

    def __str__(self):
        return self.caption
