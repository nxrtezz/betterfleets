from django.contrib import admin
from .models import Request, RequestComment, RequestHistory


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "status", "author", "created_at", "updated_at"]
    list_filter = ["category", "status", "created_at"]
    search_fields = ["title", "description", "author__username", "author__email"]
    readonly_fields = ["created_at", "updated_at", "resolved_at"]
    date_hierarchy = "created_at"
    
    fieldsets = (
        (None, {
            "fields": ("title", "description", "category", "status")
        }),
        ("Linked Objects", {
            "fields": ("vehicle", "service", "operator", "vehicle_type", "livery")
        }),
        ("Additional Details", {
            "fields": ("fleet_number", "registration", "route", "expected_behaviour")
        }),
        ("Tracking", {
            "fields": ("author", "resolved_by", "created_at", "updated_at", "resolved_at")
        }),
    )


@admin.register(RequestComment)
class RequestCommentAdmin(admin.ModelAdmin):
    list_display = ["request", "author", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["content", "author__username", "request__title"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(RequestHistory)
class RequestHistoryAdmin(admin.ModelAdmin):
    list_display = ["request", "action", "user", "created_at"]
    list_filter = ["action", "created_at"]
    search_fields = ["action", "description", "user__username", "request__title"]
    readonly_fields = ["created_at"]
