from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from vehicles.models import Vehicle

from .models import DatePrecision, EventType, VehicleHistoryEvent


@receiver(post_save, sender=Vehicle)
def generate_automatic_history_events(sender, instance, created, **kwargs):
    """
    Generate automatic VehicleHistoryEvents when vehicle fields change.
    This signal handler checks for changes in tracked fields and creates
    corresponding history events.
    """
    if created:
        # Don't generate events for new vehicles
        return

    # Get the previous state from the database
    try:
        old_instance = Vehicle.objects.get(pk=instance.pk)
    except Vehicle.DoesNotExist:
        return

    # Track which fields changed and generate appropriate events
    changes = []

    # Operator change
    if old_instance.operator_id != instance.operator_id:
        if old_instance.operator and instance.operator:
            title = f"Transferred from {old_instance.operator} to {instance.operator}"
            metadata = {
                "from_operator": old_instance.operator_id,
                "to_operator": instance.operator_id,
            }
            changes.append((EventType.TRANSFER, title, metadata))
        elif not old_instance.operator and instance.operator:
            title = f"Added to {instance.operator}"
            metadata = {"to_operator": instance.operator_id}
            changes.append((EventType.TRANSFER, title, metadata))
        elif old_instance.operator and not instance.operator:
            title = f"Removed from {old_instance.operator}"
            metadata = {"from_operator": old_instance.operator_id}
            changes.append((EventType.TRANSFER, title, metadata))

    # Livery change
    if old_instance.livery_id != instance.livery_id:
        if old_instance.livery and instance.livery:
            title = f"Repainted into {instance.livery.name}"
            metadata = {
                "from_livery": old_instance.livery_id,
                "to_livery": instance.livery_id,
            }
            changes.append((EventType.REPAINT, title, metadata))
        elif not old_instance.livery and instance.livery:
            title = f"Painted into {instance.livery.name}"
            metadata = {"to_livery": instance.livery_id}
            changes.append((EventType.REPAINT, title, metadata))
        elif old_instance.livery and not instance.livery:
            title = f"Removed {old_instance.livery.name} livery"
            metadata = {"from_livery": old_instance.livery_id}
            changes.append((EventType.REPAINT, title, metadata))

    # Garage change
    if old_instance.garage_id != instance.garage_id:
        if old_instance.garage and instance.garage:
            title = f"Transferred from {old_instance.garage.name} to {instance.garage.name}"
            metadata = {
                "from_garage": old_instance.garage_id,
                "to_garage": instance.garage_id,
            }
            changes.append((EventType.GARAGE_TRANSFER, title, metadata))
        elif not old_instance.garage and instance.garage:
            title = f"Assigned to {instance.garage.name}"
            metadata = {"to_garage": instance.garage_id}
            changes.append((EventType.GARAGE_TRANSFER, title, metadata))
        elif old_instance.garage and not instance.garage:
            title = f"Removed from {old_instance.garage.name}"
            metadata = {"from_garage": old_instance.garage_id}
            changes.append((EventType.GARAGE_TRANSFER, title, metadata))

    # Registration change
    if old_instance.reg != instance.reg:
        if old_instance.reg and instance.reg:
            title = f"Registration changed from {old_instance.reg} to {instance.reg}"
            metadata = {
                "from_registration": old_instance.reg,
                "to_registration": instance.reg,
            }
            changes.append((EventType.REGISTRATION_CHANGE, title, metadata))
        elif not old_instance.reg and instance.reg:
            title = f"Registration set to {instance.reg}"
            metadata = {"to_registration": instance.reg}
            changes.append((EventType.REGISTRATION_CHANGE, title, metadata))
        elif old_instance.reg and not instance.reg:
            title = f"Registration {old_instance.reg} removed"
            metadata = {"from_registration": old_instance.reg}
            changes.append((EventType.REGISTRATION_CHANGE, title, metadata))

    # Name change
    if old_instance.name != instance.name:
        if old_instance.name and instance.name:
            title = f"Renamed from {old_instance.name} to {instance.name}"
            metadata = {
                "from_name": old_instance.name,
                "to_name": instance.name,
            }
            changes.append((EventType.NAME_APPLIED, title, metadata))
        elif not old_instance.name and instance.name:
            title = f"Named {instance.name}"
            metadata = {"to_name": instance.name}
            changes.append((EventType.NAME_APPLIED, title, metadata))
        elif old_instance.name and not instance.name:
            title = f"Name {old_instance.name} removed"
            metadata = {"from_name": old_instance.name}
            changes.append((EventType.NAME_REMOVED, title, metadata))

    # Branding change
    if old_instance.branding != instance.branding:
        if old_instance.branding and instance.branding:
            title = f"Branding changed from {old_instance.branding} to {instance.branding}"
            metadata = {
                "from_branding": old_instance.branding,
                "to_branding": instance.branding,
            }
            changes.append((EventType.BRANDING_APPLIED, title, metadata))
        elif not old_instance.branding and instance.branding:
            title = f"Branding applied: {instance.branding}"
            metadata = {"to_branding": instance.branding}
            changes.append((EventType.BRANDING_APPLIED, title, metadata))
        elif old_instance.branding and not instance.branding:
            title = f"Branding {old_instance.branding} removed"
            metadata = {"from_branding": old_instance.branding}
            changes.append((EventType.BRANDING_REMOVED, title, metadata))

    # Withdrawn status change
    if old_instance.withdrawn != instance.withdrawn:
        if instance.withdrawn:
            title = "Withdrawn from service"
            changes.append((EventType.WITHDRAWN, title, {}))
        else:
            title = "Returned to service"
            changes.append((EventType.REINSTATED, title, {}))

    # Preserved status change
    if old_instance.preserved != instance.preserved:
        if instance.preserved:
            title = "Preserved"
            changes.append((EventType.PRESERVED, title, {}))
        else:
            title = "Removed from preservation"
            changes.append((EventType.OTHER, title, {}))

    # VOR status change
    if old_instance.vor != instance.vor:
        if instance.vor:
            title = "Vehicle off road"
            changes.append((EventType.VOR, title, {}))
        else:
            title = "Returned to service"
            changes.append((EventType.RETURNED_TO_SERVICE, title, {}))

    # Create events for each detected change
    for event_type, title, metadata in changes:
        # Check if a similar automatic event already exists recently
        # to avoid duplicate events
        recent_event = VehicleHistoryEvent.objects.filter(
            vehicle=instance,
            event_type=event_type,
            is_automatic=True,
            title=title,
        ).first()

        if not recent_event:
            VehicleHistoryEvent.objects.create(
                vehicle=instance,
                event_type=event_type,
                title=title,
                event_date=timezone.now().date(),
                date_precision=DatePrecision.DAY,
                is_automatic=True,
                metadata=metadata,
            )
