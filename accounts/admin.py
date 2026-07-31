from django.contrib import admin
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse, path
from django.utils.html import format_html
from sql_util.utils import SubqueryCount

from .models import APIKey, OperatorUser, ProfileTag, User, DriverStatusRequest


def get_count(obj, attribute, approved):
    return format_html(
        '<a href="{}?user={}&{}">{}</a>',
        reverse("admin:vehicles_vehiclerevision_changelist"),
        obj.id,
        approved,
        getattr(obj, attribute, None),
    )


class OperatorUserInline(admin.TabularInline):
    model = OperatorUser
    raw_id_fields = ["operator"]


class APIKeyInline(admin.TabularInline):
    model = APIKey
    extra = 0
    readonly_fields = ["key", "created_at", "last_used_at"]


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    raw_id_fields = ["user_permissions"]
    actions = ["trust", "distrust"]
    search_fields = ["username", "email"]
    readonly_fields = ["revisions", "disapproved", "pending"]
    base_list_display = [
        "id",
        "display_name",
        "username",
        "email",
        "last_login",
        "is_active",
        "score",
        "trusted",
    ]
    list_display_links = ["id", "username"]
    inlines = [OperatorUserInline, APIKeyInline]
    base_list_filter = [
        "trusted",
        "is_staff",
        "groups",
        ("user_permissions", admin.RelatedOnlyFieldListFilter),
    ]
    filter_horizontal = ["manual_tags"]
    change_form_template = "admin/accounts/user/change_form.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/bypass-new-account-restriction/",
                self.admin_site.admin_view(self.bypass_new_account_restriction),
                name="accounts_user_bypass_new_account_restriction",
            ),
        ]
        return custom_urls + urls

    def bypass_new_account_restriction(self, request, object_id):
        from django.shortcuts import get_object_or_404
        import datetime

        user = get_object_or_404(User, pk=object_id)
        user.date_joined = user.date_joined - datetime.timedelta(hours=1)
        user.save(update_fields=["date_joined"])
        self.message_user(request, "Account creation time pushed back by 1 hour")
        return HttpResponseRedirect(
            reverse("admin:accounts_user_change", args=[object_id])
        )

    def _has_blocked_from_reviews_field(self):
        try:
            self.model._meta.get_field("blocked_from_reviews")
        except Exception:
            return False
        return True

    def get_list_display(self, request):
        list_display = list(self.base_list_display)
        if self._has_blocked_from_reviews_field():
            list_display.insert(6, "blocked_from_reviews")
        return list_display + list(self.readonly_fields)

    def get_list_filter(self, request):
        list_filter = list(self.base_list_filter)
        if self._has_blocked_from_reviews_field():
            list_filter.insert(1, "blocked_from_reviews")
        return list_filter

    @admin.display(ordering="revisions")
    def revisions(self, obj):
        return get_count(obj, "revisions", "")

    @admin.display(ordering="disapproved")
    def disapproved(self, obj):
        return get_count(obj, "disapproved", "disapproved=True")

    @admin.display(ordering="pending")
    def pending(self, obj):
        return get_count(obj, "pending", "pending=True")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.resolver_match.view_name in (
            "admin:accounts_user_changelist",
            "admin:accounts_user_change",
        ):
            queryset = queryset.annotate(
                disapproved=SubqueryCount(
                    "vehiclerevision", filter=Q(disapproved=True)
                ),
                pending=SubqueryCount("vehiclerevision", filter=Q(pending=True)),
                revisions=SubqueryCount("vehiclerevision"),
            )
        return queryset

    def trust(self, request, queryset):
        count = queryset.order_by().update(trusted=True)
        self.message_user(request, f"Trusted {count} users")

    def distrust(self, request, queryset):
        count = queryset.order_by().update(trusted=False)
        self.message_user(request, f"Disusted {count} users")


@admin.register(OperatorUser)
class OperatorUserAdmin(admin.ModelAdmin):
    raw_id_fields = ["user", "operator"]


@admin.register(ProfileTag)
class ProfileTagAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "badge_background", "badge_text_colour", "user_count"]
    search_fields = ["name", "slug"]
    filter_horizontal = ["users"]

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "users":
            from .models import User
            kwargs["queryset"] = User.objects.order_by("id")
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def user_count(self, obj):
        return obj.users.count()
    user_count.short_description = "Users"


@admin.register(DriverStatusRequest)
class DriverStatusRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "approved", "approved_by", "approved_at")
    list_filter = ("approved", "created_at")
    search_fields = ("user__email", "user__username", "user__display_name")
    readonly_fields = ("created_at",)
    actions = ("approve_requests", "deny_requests")

    def approve_requests(self, request, queryset):
        count = 0
        for driver_request in queryset.filter(approved__isnull=True):
            # Allow superusers to approve their own requests
            if request.user.id == driver_request.user_id and not request.user.is_superuser:
                continue
            driver_request.approved = True
            driver_request.approved_by = request.user
            driver_request.approved_at = timezone.now()
            driver_request.user.is_driver = True
            driver_request.user.save(update_fields=["is_driver"])
            driver_request.save()
            count += 1
        self.message_user(request, f"Approved {count} driver status request(s).")

    def deny_requests(self, request, queryset):
        count = queryset.filter(approved__isnull=True).update(approved=False)
        self.message_user(request, f"Denied {count} driver status request(s).")


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "created_at", "last_used_at", "is_active"]
    list_filter = ["is_active", "created_at"]
    search_fields = ["name", "user__email", "user__username"]
    readonly_fields = ["key", "created_at", "last_used_at"]
    raw_id_fields = ["user"]
