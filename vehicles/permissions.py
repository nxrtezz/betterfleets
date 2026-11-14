"""Vehicle edit approval policy shared by views and templates."""

REVIEW_PERMISSION = "vehicles.approve_vehicle_edits"


def operator_ids(user):
    if not user.is_authenticated or not user.is_active or user.trusted is False:
        return set()
    if not hasattr(user, "_edit_operator_ids"):
        user._edit_operator_ids = set(user.operators.values_list("pk", flat=True))
    return user._edit_operator_ids


def can_review_revision(user, revision):
    if not user.is_authenticated or not user.is_active or user.trusted is False:
        return False
    if user.has_perm(REVIEW_PERMISSION):
        return True
    affected = {revision.from_operator_id, revision.to_operator_id}
    if revision.vehicle_id:
        affected.add(revision.vehicle.operator_id)
    affected.discard(None)
    return bool(affected) and affected <= operator_ids(user)


def can_auto_approve_revision(user, revision):
    return (user.is_authenticated and user.is_active and user.trusted is not False
            and revision.user_id == user.pk
            and (user.trusted is True or can_review_revision(user, revision)))
