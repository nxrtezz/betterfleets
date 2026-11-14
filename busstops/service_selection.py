"""Canonical selection for overlapping Southern Vectis timetable publications."""
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from bustimes.models import Route


def prefer_svct_timetables(services, when=None):
    """Prefer the current non-versioned publication over the Passenger export of the same public line.

    This does not delete or alter either feed. Unique lines, different modes,
    other operators, and Passenger fallbacks without a usable preferred route survive.
    """
    when = when or timezone.localdate()
    passenger = Route.objects.filter(service=OuterRef("pk"), version__isnull=False)
    preferred = Route.objects.active_on(when).filter(
        service__operator="SVCT",
        service__current=True,
        service__line_name__iexact=OuterRef("line_name"),
        service__mode=OuterRef("mode"),
        version__isnull=True,
        trip__isnull=False,
    ).exclude(service=OuterRef("pk"))
    return services.exclude(
        Q(operator="SVCT") & Exists(passenger) & Exists(preferred)
    )
