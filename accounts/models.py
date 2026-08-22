from types import SimpleNamespace
from urllib.parse import urlencode
import random
import string

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.urls import reverse
from django.utils import timezone
from uuid import uuid4
import secrets


class CustomUserManager(UserManager):
    def get_by_natural_key(self, username):
        # Try to find user by email first (case-insensitive)
        try:
            return self.get(email__iexact=username)
        except self.model.DoesNotExist:
            # If not found by email, try to find by username (case-insensitive)
            return self.get(username__iexact=username)


class DiscordLinkCode(models.Model):
    code = models.CharField(max_length=6, unique=True)
    user = models.ForeignKey("User", models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not self.expires_at:
            from datetime import timedelta
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def __str__(self):
        return self.code


class DriverStatusRequest(models.Model):
    user = models.ForeignKey("User", models.CASCADE, related_name="driver_requests")
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved = models.BooleanField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "User",
        models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_driver_requests",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Driver request by {self.user}"


class OperatorUser(models.Model):
    operator = models.ForeignKey("busstops.Operator", models.CASCADE)
    user = models.ForeignKey("User", models.CASCADE)
    staff = models.BooleanField(default=False)


class ProfileTag(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)
    badge_background = models.CharField(max_length=7, default="#334155")
    badge_text_colour = models.CharField(max_length=7, default="#ffffff")
    users = models.ManyToManyField("User", blank=True, related_name="profile_tags")

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class User(AbstractUser):
    email = models.EmailField(unique=True, verbose_name="email address")
    trusted = models.BooleanField(null=True)
    display_name = models.CharField(max_length=80, blank=True)
    profile_picture = models.ImageField(
        upload_to="users/profile-pictures", blank=True, null=True
    )
    profile_banner = models.ImageField(
        upload_to="users/profile-banners", blank=True, null=True
    )
    flickr_username = models.CharField(max_length=100, blank=True)
    discord_username = models.CharField(max_length=100, blank=True)
    discord_user_id = models.CharField(max_length=32, blank=True)
    fleet_logging_public = models.BooleanField(default=True)
    driving_logging_public = models.BooleanField(default=True)
    blocked_from_reviews = models.BooleanField(default=False)
    operators = models.ManyToManyField(
        "busstops.Operator", blank=True, through=OperatorUser
    )
    manual_tags = models.ManyToManyField(ProfileTag, blank=True, related_name="tagged_users")
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    score = models.IntegerField(blank=True, null=True)
    is_driver = models.BooleanField(default=False)
    view_advanced = models.BooleanField(default=False, help_text="Enable advanced editing controls")
    advanced_mode = models.BooleanField(default=False, help_text="Enable advanced fleet export features")
    objects = CustomUserManager()

    USERNAME_FIELD = "email"  # this was a bad idea
    REQUIRED_FIELDS = ["username"]  # so that ./manage.py createsuperuser works

    def get_absolute_url(self):
        return reverse("user_detail", args=(self.id,))

    def get_username_display(self):
        if self.username and self.username != self.email:
            return self.username
        return f"user{self.id}"

    def get_display_name(self):
        return self.display_name or self.get_username_display()

    def get_full_name_display(self):
        return " ".join(part for part in (self.first_name, self.last_name) if part).strip()

    def get_profile_banner_url(self):
        if self.profile_banner:
            return self.profile_banner.url
        return ""

    def get_profile_picture_url(self):
        if self.profile_picture:
            return self.profile_picture.url
        return ""

    def get_flickr_profile_url(self):
        if not self.flickr_username:
            return ""
        return f"https://www.flickr.com/people/{self.flickr_username}/"

    def get_discord_widget_url(self):
        if not self.discord_user_id:
            return ""
        params = urlencode(
            {
                "id": self.discord_user_id,
                "theme": "dark",
                "banner": "true",
                "rounded-corners": "true",
                "discord-icon": "true",
                "badges": "true",
            }
        )
        return f"https://widgets.vendicated.dev/user?{params}"

    def get_review_master_eligible(self):
        review_count = getattr(self, "_review_count", None)
        reviewed_operator_count = getattr(self, "_reviewed_operator_count", None)
        if review_count is None:
            review_count = self.vehicle_reviews.count()
        if reviewed_operator_count is None:
            reviewed_operator_count = (
                self.vehicle_reviews.exclude(vehicle__operator__isnull=True)
                .values("vehicle__operator_id")
                .distinct()
                .count()
            )
        return review_count >= 50 or (review_count >= 5 and reviewed_operator_count >= 5)

    def get_profile_tags(self):
        tags = []
        if self.trusted:
            tags.append(
                SimpleNamespace(
                    name="Trusted",
                    slug="trusted",
                    description="Trusted contributor",
                    badge_background="#1f9d55",
                    badge_text_colour="#ffffff",
                    automatic=True,
                )
            )
        if self.get_review_master_eligible():
            tags.append(
                SimpleNamespace(
                    name="Review Master",
                    slug="review-master",
                    description="Awarded for prolific review activity",
                    badge_background="#facc15",
                    badge_text_colour="#1f2937",
                    automatic=True,
                )
            )
        tags.extend(self.profile_tags.all())
        return tags

    def __str__(self):
        return self.get_display_name()


class APIKey(models.Model):
    """API key for authenticating API requests"""
    key = models.CharField(max_length=64, unique=True, editable=False)
    name = models.CharField(max_length=100, help_text="A name to identify this API key")
    user = models.ForeignKey(User, models.CASCADE, related_name="api_keys")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.user})"

    class Meta:
        ordering = ("-created_at",)
