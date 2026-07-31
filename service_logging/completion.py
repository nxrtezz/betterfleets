from django.contrib.postgres.aggregates import BoolOr
from django.db.models.functions import Coalesce

from busstops.models import Service

from .models import ServiceLog


def get_user_route_stats(user) -> dict:
    """Return route-completion totals for a user's public profile."""
    public_routes = Service.objects.annotate(
        actual_public_use=Coalesce("public_use", BoolOr("route__public_use"), True)
    ).exclude(actual_public_use=False)
    ridden_routes = ServiceLog.objects.filter(user=user, ridden=True)
    total_public_routes = public_routes.count()
    ridden_non_public_routes = ridden_routes.exclude(
        service_id__in=public_routes.values("id")
    ).count()
    completion_total = total_public_routes + ridden_non_public_routes
    ridden_total = ridden_routes.count()

    return {
        "ridden": ridden_total,
        "public_total": total_public_routes,
        "overall_total": completion_total,
        "overall_percentage": (ridden_total / completion_total * 100)
        if completion_total
        else 0,
    }
