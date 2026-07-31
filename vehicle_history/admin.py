from django.contrib import admin

from .models import DatePrecision, EventType, VehicleHistoryAttachment, VehicleHistoryEvent


@admin.register(VehicleHistoryEvent)
class VehicleHistoryEventAdmin(admin.ModelAdmin):
    list_display = [
        "vehicle",
        "event_type",
        "title",
        "event_date",
        "date_precision",
        "is_future_event",
        "is_automatic",
        "created_by",
        "created_at",
    ]
    list_filter = [
        "event_type",
        "date_precision",
        "is_future_event",
        "is_automatic",
        "event_date",
        "created_at",
    ]
    search_fields = [
        "vehicle__code",
        "vehicle__reg",
        "vehicle__fleet_code",
        "title",
        "description",
        "created_by__username",
    ]
    date_hierarchy = "event_date"
    readonly_fields = ["created_at", "updated_at"]
    fieldsets = (
        (
            "Basic Information",
            {
                "fields": (
                    "vehicle",
                    "event_type",
                    "title",
                    "description",
                )
            },
        ),
        (
            "Date Information",
            {
                "fields": (
                    "event_date",
                    "date_precision",
                    "is_future_event",
                )
            },
        ),
        (
            "Event Details",
            {
                "fields": (
                    "is_automatic",
                    "created_by",
                    "metadata",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("vehicle", "created_by")


@admin.register(VehicleHistoryAttachment)
class VehicleHistoryAttachmentAdmin(admin.ModelAdmin):
    list_display = [
        "event",
        "photo",
        "caption",
    ]
    list_filter = ["event__event_type"]
    search_fields = [
        "event__title",
        "event__vehicle__code",
        "event__vehicle__reg",
        "caption",
    ]
    readonly_fields = []

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("event", "photo")
