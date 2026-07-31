from django.core.cache import cache
from django.db.models.signals import m2m_changed, post_save
from django.dispatch import receiver

from .models import Livery, Vehicle


@receiver(post_save, sender=Livery)
def liveries_cache_update(sender, instance, **kwargs):
    cache.set("liveries_css_version", int(instance.updated_at.timestamp()), None)


@receiver(post_save, sender=Vehicle)
def vehicle_cache_update(sender, instance, created, **kwargs):
    if not created and instance.latest_journey_id:
        cache.delete(f"journey{instance.latest_journey_id}")


@receiver(m2m_changed, sender=Vehicle.features.through)
def sync_fleet_support_status(sender, instance, action, reverse, pk_set, **kwargs):
    if reverse or "fleet_support_vehicle" in instance.missing_db_fields():
        return

    if action == "post_add" and 8 in pk_set and not instance.fleet_support_vehicle:
        Vehicle.objects.filter(pk=instance.pk).update(fleet_support_vehicle=True)
        instance.fleet_support_vehicle = True
    elif action in ("post_remove", "post_clear"):
        has_fleet_support_feature = instance.features.filter(pk=8).exists()
        if instance.fleet_support_vehicle != has_fleet_support_feature:
            Vehicle.objects.filter(pk=instance.pk).update(
                fleet_support_vehicle=has_fleet_support_feature
            )
            instance.fleet_support_vehicle = has_fleet_support_feature
