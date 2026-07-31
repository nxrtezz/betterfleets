from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from accounts.scoring import update_user_score


@receiver(post_save, sender="vehicles.VehicleRevision")
def update_score_on_revision_save(sender, instance, created, **kwargs):
    """
    Update user score when a revision is saved (created or updated).
    """
    if instance.user:
        update_user_score(instance.user)


@receiver(post_delete, sender="vehicles.VehicleRevision")
def update_score_on_revision_delete(sender, instance, **kwargs):
    """
    Update user score when a revision is deleted.
    """
    if instance.user:
        update_user_score(instance.user)


@receiver(post_save, sender="vehicles.VehicleReview")
def update_score_on_review_save(sender, instance, created, **kwargs):
    """
    Update user score when a review is saved (created or updated).
    """
    if instance.user:
        update_user_score(instance.user)


@receiver(post_delete, sender="vehicles.VehicleReview")
def update_score_on_review_delete(sender, instance, **kwargs):
    """
    Update user score when a review is deleted.
    """
    if instance.user:
        update_user_score(instance.user)
