def get_vehicle_identity(item: dict) -> str:
    monitored_vehicle_journey = item["MonitoredVehicleJourney"]
    operator_ref = monitored_vehicle_journey["OperatorRef"]
    vehicle_ref = monitored_vehicle_journey["VehicleRef"]

    try:
        vehicle_unique_id = item["Extensions"]["VehicleJourney"]["VehicleUniqueId"]
    except (KeyError, TypeError):
        pass
    else:
        vehicle_ref = f"{vehicle_ref}:{vehicle_unique_id}"

    return f"{operator_ref}:{vehicle_ref}"


def get_journey_identity(item: dict) -> str:
    monitored_vehicle_journey = item["MonitoredVehicleJourney"]
    line_ref = monitored_vehicle_journey.get("LineRef")
    line_name = monitored_vehicle_journey.get("PublishedLineName")

    try:
        journey_ref = monitored_vehicle_journey["FramedVehicleJourneyRef"]
    except (KeyError, ValueError):
        journey_ref = monitored_vehicle_journey.get("VehicleJourneyRef")

    departure = monitored_vehicle_journey.get("OriginAimedDepartureTime")
    direction = monitored_vehicle_journey.get("DirectionRef")
    destination = monitored_vehicle_journey.get("DestinationName")

    return f"{line_ref} {line_name} {journey_ref} {departure} {direction} {destination}"


def get_item_identity(item: dict) -> str:
    return item["RecordedAtTime"]
