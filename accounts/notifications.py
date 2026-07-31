import logging

import requests
from django.conf import settings
from django.utils import timezone


logger = logging.getLogger(__name__)


def _get_public_url(path):
    base_url = getattr(settings, "BUSTIMES_API_BASE_URL", "https://betterfleets.org").rstrip("/")
    return f"{base_url}{path}"


def _post_discord_embed(webhook_url, *, title, description="", color=0x2563EB, fields=None, url="", components=None):
    if not webhook_url:
        return

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": timezone.now().isoformat(),
        "fields": fields or [],
    }
    if url:
        embed["url"] = url

    payload = {"embeds": [embed]}
    if components:
        payload["components"] = components

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to send Discord webhook", extra={"title": title})


def notify_new_user(user):
    webhook_url = settings.NEW_USER_WEBHOOK_URL
    fields = [
        {"name": "Email", "value": user.email, "inline": False},
        {"name": "User ID", "value": str(user.id), "inline": True},
        {"name": "Display Name", "value": user.get_display_name(), "inline": True},
    ]
    if user.username:
        fields.append({"name": "Username", "value": user.username, "inline": True})

    _post_discord_embed(
        webhook_url,
        title="New user signup",
        description=f"{user.get_display_name()} just created an account.",
        color=0x22C55E,
        fields=fields,
        url=_get_public_url(user.get_absolute_url()),
    )


def notify_request_created(
    *,
    request_type,
    target_title,
    summary,
    user,
    changes,
):
    webhook_url = settings.REQUEST_WEBHOOK_URL
    details = []
    for label, change in (changes or {}).items():
        value = (change or {}).get("to")
        if value in ("", None):
            continue
        details.append(f"**{str(label).replace('_', ' ').title()}:** {value}")

    fields = [
        {"name": "Type", "value": request_type, "inline": True},
        {"name": "Requested By", "value": f"{user.get_display_name()} (`{user.email}`)", "inline": False},
        {"name": "Target", "value": target_title, "inline": False},
    ]
    if summary:
        fields.append({"name": "Summary", "value": summary, "inline": False})
    if details:
        fields.append(
            {
                "name": "Details",
                "value": "\n".join(details)[:1024],
                "inline": False,
            }
        )

    _post_discord_embed(
        webhook_url,
        title=f"New {request_type.lower()} request",
        description=f"{user.get_display_name()} submitted a request for {target_title}.",
        color=0xF59E0B,
        fields=fields,
        url=_get_public_url("/requests"),
    )


def notify_vehicle_revision(revision, action="created"):
    webhook_url = settings.REQUEST_WEBHOOK_URL
    vehicle = revision.vehicle

    if action == "created":
        color = 0x3B82F6  # Blue for new revisions
        title = f"New Vehicle Revision: {vehicle}"
        description = f"{revision.user.get_display_name()} submitted a revision for {vehicle}."
    elif action == "approved":
        color = 0x22C55E  # Green for approved
        title = f"Vehicle Revision Approved: {vehicle}"
        description = f"Revision for {vehicle} has been approved."
    elif action == "disapproved":
        color = 0xEF4444  # Red for disapproved
        title = f"Vehicle Revision Disapproved: {vehicle}"
        description = f"Revision for {vehicle} has been disapproved."
    else:
        color = 0x6B7280  # Gray for other actions
        title = f"Vehicle Revision: {vehicle}"
        description = f"Revision for {vehicle} has been {action}."

    fields = [
        {"name": "Vehicle", "value": str(vehicle), "inline": True},
        {"name": "Submitted By", "value": revision.user.get_display_name() if revision.user else "Unknown", "inline": True},
    ]

    if revision.to_operator:
        fields.append({"name": "Operator", "value": revision.to_operator.name, "inline": True})
    if revision.to_type:
        fields.append({"name": "Type", "value": revision.to_type.name, "inline": True})
    if revision.to_livery:
        fields.append({"name": "Livery", "value": revision.to_livery.name, "inline": True})
    if revision.message:
        fields.append({"name": "Message", "value": revision.message[:1024], "inline": False})

    # Add approve/deny buttons for pending revisions
    components = None
    if action == "created" and revision.pending:
        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 3,
                        "label": "Approve",
                        "custom_id": f"approve_revision_{revision.id}",
                    },
                    {
                        "type": 2,
                        "style": 4,
                        "label": "Deny",
                        "custom_id": f"deny_revision_{revision.id}",
                    },
                ]
            }
        ]

    _post_discord_embed(
        webhook_url,
        title=title,
        description=description,
        color=color,
        fields=fields,
        url=_get_public_url(vehicle.get_absolute_url()),
        components=components,
    )
