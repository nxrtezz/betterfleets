from django.contrib import admin
from .models import Photo


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ["flickr_url", "credit", "caption", "created_at"]
    list_filter = ["created_at", "license"]
    search_fields = ["flickr_url", "credit", "caption"]
    raw_id_fields = ["vehicles", "livery", "vehicle_type", "service", "user"]
    fieldsets = (
        (None, {
            "fields": ("flickr_url", "credit", "caption", "created_at", "license")
        }),
        ("Relations", {
            "fields": ("vehicles", "livery", "vehicle_type", "service", "user")
        }),
    )
