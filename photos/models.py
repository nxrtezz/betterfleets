from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill
import requests
from io import BytesIO
from PIL import Image
import re
from bs4 import BeautifulSoup


def validate_flickr_url(value):
    """Validate that the URL is from Flickr."""
    if value and "flickr.com" not in value.lower():
        raise ValidationError("Only Flickr URLs are allowed for photos.")


def download_image_from_flickr(flickr_url):
    """Download the main image from a Flickr URL by parsing the page HTML."""
    try:
        # Fetch the Flickr page
        response = requests.get(flickr_url, timeout=10)
        response.raise_for_status()
        
        # Parse the HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find the main photo img tag with class "main-photo"
        main_photo = soup.find('img', class_='main-photo')
        if not main_photo:
            raise ValidationError("Could not find main photo on Flickr page")
        
        # Get the image URL
        img_url = main_photo.get('src')
        if not img_url:
            raise ValidationError("Could not find image source URL")
        
        # Add https:// if the URL starts with //
        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        
        # Extract title and author from alt text
        # Format: "Title | by Author" or "Title, Location, Date | by Author"
        alt_text = main_photo.get('alt', '')
        title = ''
        author = ''
        
        if alt_text:
            # Split by " | by " to separate title from author
            if ' | by ' in alt_text:
                parts = alt_text.split(' | by ')
                title = parts[0].strip()
                author = parts[1].strip() if len(parts) > 1 else ''
            else:
                title = alt_text
        
        # Download the image
        img_response = requests.get(img_url, timeout=10)
        img_response.raise_for_status()
        
        return Image.open(BytesIO(img_response.content)), title, author
        
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
            img, title, author = download_image_from_flickr(self.flickr_url)
            
            # Set title and author if not already provided
            if not self.caption and title:
                self.caption = title
            if not self.credit and author:
                self.credit = author
            
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
