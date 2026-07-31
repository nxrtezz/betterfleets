import requests

from django.utils import timezone


DEFAULT_DVLA_URL = "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles"
DEFAULT_DVLA_USER_AGENT = "betterfleet/1.0 (+https://betterfleet.example)"


def get_dvla_headers(api_key: str, user_agent: str = DEFAULT_DVLA_USER_AGENT) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }


def fetch_dvla_record(
    registration: str,
    *,
    api_key: str,
    url: str = DEFAULT_DVLA_URL,
    user_agent: str = DEFAULT_DVLA_USER_AGENT,
) -> dict:
    response = requests.post(
        url,
        headers=get_dvla_headers(api_key, user_agent=user_agent),
        json={"registrationNumber": registration},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def build_dvla_update(vehicle, payload: dict, checked_at=None) -> dict:
    checked_at = checked_at or timezone.now()
    
    # Map DVLA fuel types to our fuel types
    dvla_fuel_type = payload.get("fuelType", "").upper()
    fuel_type_mapping = {
        "PETROL": "diesel",
        "DIESEL": "diesel",
        "ELECTRIC": "electric",
        "HYBRID": "hybrid",
        "HYDROGEN": "hydrogen",
        "GAS": "gas",
    }
    fuel_type = fuel_type_mapping.get(dvla_fuel_type, "")
    
    return {
        "vehicle": vehicle,
        "registration": vehicle.reg,
        "tax_status": payload.get("taxStatus", "") or "",
        "mot_status": payload.get("motStatus", "") or "",
        "euro_status": payload.get("euroStatus", "") or "",
        "year_of_manufacture": payload.get("yearOfManufacture"),
        "fuel_type": fuel_type,
        "checked_at": checked_at,
    }
