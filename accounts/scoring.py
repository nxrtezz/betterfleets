from django.db import models
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta


# Scoring rules
SCORE_RULES = {
    "revision_approved": 10,
    "revision_disapproved": -5,
    "review_published": 5,
    "review_hidden": -2,
    "review_pending": 0,
}


def calculate_user_score(user):
    """
    Calculate a user's score out of 100 based on their approved/disapproved edit ratio.
    If a disapproved edit was longer than 1 month ago, don't count it into their score
    ONLY if they've made the same amount or more of approved edits.
    """
    from vehicles.models import VehicleRevision, VehicleReview
    
    # Score from revisions
    approved_revisions = VehicleRevision.objects.filter(
        user=user, pending=False, disapproved=False
    ).count()
    
    # Get disapproved revisions older than 1 month
    one_month_ago = timezone.now() - timedelta(days=30)
    old_disapproved_revisions = VehicleRevision.objects.filter(
        user=user, disapproved=True, created_at__lt=one_month_ago
    ).count()
    
    # Get recent disapproved revisions (within last month)
    recent_disapproved_revisions = VehicleRevision.objects.filter(
        user=user, disapproved=True, created_at__gte=one_month_ago
    ).count()
    
    # If user has same or more approved edits than old disapproved, ignore old disapproved
    if approved_revisions >= old_disapproved_revisions:
        disapproved_revisions = recent_disapproved_revisions
    else:
        disapproved_revisions = old_disapproved_revisions + recent_disapproved_revisions
    
    # Calculate score out of 100 based on ratio
    if approved_revisions == 0 and disapproved_revisions == 0:
        return 50  # Neutral score for new users
    elif approved_revisions == 0:
        return 0  # No approved edits
    elif disapproved_revisions == 0:
        return 100  # Perfect score
    
    # Calculate ratio-based score
    total_edits = approved_revisions + disapproved_revisions
    ratio = approved_revisions / total_edits
    score = int(ratio * 100)
    
    return score


def update_user_score(user):
    """
    Update a user's score in the database.
    """
    score = calculate_user_score(user)
    user.score = score
    user.save(update_fields=["score"])
    return score


def get_score_breakdown(user):
    """
    Get a detailed breakdown of a user's score.
    """
    from vehicles.models import VehicleRevision, VehicleReview
    
    # Revision breakdown
    approved_revisions = VehicleRevision.objects.filter(
        user=user, pending=False, disapproved=False
    ).count()
    disapproved_revisions = VehicleRevision.objects.filter(
        user=user, disapproved=True
    ).count()
    pending_revisions = VehicleRevision.objects.filter(
        user=user, pending=True
    ).count()
    
    # Review breakdown
    published_reviews = VehicleReview.objects.filter(
        user=user, status=VehicleReview.Status.PUBLISHED
    ).count()
    hidden_reviews = VehicleReview.objects.filter(
        user=user, status=VehicleReview.Status.HIDDEN
    ).count()
    pending_reviews = VehicleReview.objects.filter(
        user=user, status=VehicleReview.Status.PENDING
    ).count()
    
    return {
        "total_score": user.score or calculate_user_score(user),
        "revision_score": (
            approved_revisions * SCORE_RULES["revision_approved"]
            + disapproved_revisions * SCORE_RULES["revision_disapproved"]
        ),
        "review_score": (
            published_reviews * SCORE_RULES["review_published"]
            + hidden_reviews * SCORE_RULES["review_hidden"]
        ),
        "approved_revisions": approved_revisions,
        "disapproved_revisions": disapproved_revisions,
        "pending_revisions": pending_revisions,
        "published_reviews": published_reviews,
        "hidden_reviews": hidden_reviews,
        "pending_reviews": pending_reviews,
    }


def get_leaderboard(limit=50):
    """
    Get the top users by score.
    """
    from accounts.models import User
    
    return User.objects.filter(
        score__isnull=False
    ).exclude(
        score=0
    ).order_by("-score")[:limit]


def recalculate_all_scores():
    """
    Recalculate scores for all users. This is useful for fixing inconsistencies.
    """
    from accounts.models import User
    
    users_updated = 0
    for user in User.objects.all():
        update_user_score(user)
        users_updated += 1
    
    return users_updated
