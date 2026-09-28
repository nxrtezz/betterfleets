import logging

import requests
from django.conf import settings
from huey.contrib.djhuey import db_task

logger = logging.getLogger(__name__)


def vehicle_url(vehicle):
    # Use the actual site domain instead of hardcoded betterfleets.org
    from django.conf import settings
    domain = getattr(settings, 'SITE_DOMAIN', 'eeveeit.uk')
    return f"https://{domain}{vehicle.get_absolute_url()}"


def vehicle_embed(vehicle, title, description):
    embed = {
        "title": title,
        "description": description,
        "url": vehicle_url(vehicle),
        "color": 0x2563EB,
        "fields": [],
    }
    if vehicle.reg:
        embed["fields"].append({"name": "Registration", "value": vehicle.reg, "inline": True})
    if vehicle.fleet_number or vehicle.fleet_code:
        embed["fields"].append(
            {
                "name": "Fleet number",
                "value": str(vehicle.fleet_number or vehicle.fleet_code),
                "inline": True,
            }
        )
    if vehicle.operator:
        embed["fields"].append({"name": "Operator", "value": str(vehicle.operator), "inline": True})
    if vehicle.vehicle_type:
        embed["fields"].append({"name": "Type", "value": str(vehicle.vehicle_type), "inline": True})
    return embed


def send_alert_embed(embed):
    webhook_url = settings.DISCORD_NOTIFICATIONS_WEBHOOK_URL
    if not webhook_url:
        return

    try:
        response = requests.post(
            webhook_url,
            json={"embeds": [embed]},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Could not send BetterFleets Discord alert")


@db_task()
def notify_new_vehicle(vehicle_id):
    from vehicles.models import Vehicle

    vehicle = Vehicle.objects.select_related("operator", "vehicle_type").get(pk=vehicle_id)
    send_alert_embed(
        vehicle_embed(
            vehicle,
            "New vehicle added",
            f"{vehicle} has been added to BetterFleets.",
        )
    )


@db_task()
def notify_first_tracking(vehicle_id):
    from vehicles.models import Vehicle

    vehicle = Vehicle.objects.select_related("operator", "vehicle_type").get(pk=vehicle_id)
    send_alert_embed(
        vehicle_embed(
            vehicle,
            "Vehicle tracking started",
            f"{vehicle} has been tracked for the first time.",
        )
    )
