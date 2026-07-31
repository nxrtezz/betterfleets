from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from vehicles.models import Vehicle

from .request_context import get_current_user, is_admin_request
from .vehicle_revision_logging import log_vehicle_revision, snapshot_vehicle


def get_sync_revision_user():
    return get_user_model().objects.filter(pk=1).first()


@receiver(pre_save, sender=Vehicle)
def remember_vehicle_revision_before(sender, instance, raw=False, **kwargs):
    if raw or getattr(instance, "_skip_revision_logging", False):
        return
    if instance.pk:
        try:
            before = snapshot_vehicle(sender.objects.get(pk=instance.pk))
        except sender.DoesNotExist:
            before = {field: None for field in snapshot_vehicle(instance)}
    else:
        before = {field: None for field in snapshot_vehicle(instance)}
    instance._revision_before = before


@receiver(post_save, sender=Vehicle)
def log_vehicle_save_revision(sender, instance, raw=False, **kwargs):
    if raw or getattr(instance, "_skip_revision_logging", False):
        return

    before = getattr(instance, "_revision_before", None)
    if before is None:
        return

    request_user = get_current_user()
    if request_user and not is_admin_request():
        return
    user = request_user or get_sync_revision_user()

    message = "Django admin edit" if request_user else "Management command edit"
    log_vehicle_revision(instance, before, user=user, message=message)
