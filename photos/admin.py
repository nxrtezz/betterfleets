from django.contrib import admin
from .models import Photo


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ["caption", "credit", "flickr_url", "created_at"]
    list_filter = ["created_at", "license"]
    search_fields = ["caption", "credit", "flickr_url"]
    raw_id_fields = ["vehicles", "livery", "vehicle_type", "service", "user"]
    fieldsets = (
        (None, {
            "fields": ("flickr_url", "image", "caption", "credit", "created_at", "license")
        }),
        ("Relations", {
            "fields": ("vehicles", "livery", "vehicle_type", "service", "user")
        }),
    )
    readonly_fields = ["image"]  # Image is auto-downloaded from Flickr URL
