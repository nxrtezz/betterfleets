from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import LiveVehicleLocation
from vehicles.models import Vehicle


@receiver(post_save, sender=LiveVehicleLocation)
def notify_first_vehicle_tracking(sender, instance, created, **kwargs):
    if not created:
        return

    from .notifications import notify_first_tracking

    marked = Vehicle.objects.filter(
        pk=instance.vehicle_id,
        first_tracked_at__isnull=True,
    ).update(first_tracked_at=timezone.now())
    if marked:
        transaction.on_commit(lambda: notify_first_tracking(instance.vehicle_id))
