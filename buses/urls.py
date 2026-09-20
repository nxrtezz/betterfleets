from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from api import api


@require_GET
def clerk_config(request):
    """Expose the public Clerk key in a safe, read-only JSON endpoint."""
    return JsonResponse({
        "publishableKey": settings.CLERK_PUBLISHABLE_KEY,
        "enabled": bool(settings.CLERK_PUBLISHABLE_KEY),
    })


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("accounts.urls")),
    path("clerk/config/", clerk_config, name="clerk_config"),
    path("api/", include(api.router.urls)),
    path("tools/", include("tools.urls")),
    path("favourites/", include("favourites.urls")),
    path("service-logging/", include("service_logging.urls")),
    path("", include("busstops.urls")),
    path("", include("vehicles.urls")),
    path("", include("bustimes.urls")),
    path("service-requests/", include("service_requests.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = "busstops.views.not_found"