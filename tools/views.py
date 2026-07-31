from busstops.bustimes_sync import BustimesApiClient
from django.shortcuts import render


def block_view(request):
    operator_id = request.GET.get("operator")
    garage_id = request.GET.get("garage")
    
    vehicles_data = []
    
    if operator_id:
        client = BustimesApiClient()
        
        try:
            # Fetch vehicles from bustimes API
            params = {"operator": operator_id}
            if garage_id:
                params["garage"] = garage_id
            
            vehicles = list(client.iter_results("vehicles", params=params))
            
            # Build a mapping of vehicle IDs to vehicle data
            vehicle_map = {}
            for vehicle in vehicles:
                if vehicle is None:
                    continue
                vehicle_id = vehicle.get("id")
                if not vehicle_id:
                    continue
                vehicle_map[vehicle_id] = {
                    "fleet_code": vehicle.get("fleet_code", "Unknown"),
                    "reg": vehicle.get("reg", ""),
                    "livery_left": (vehicle.get("livery") or {}).get("left", ""),
                    "livery_right": (vehicle.get("livery") or {}).get("right", ""),
                    "blocks": set(),
                }
            
            # Fetch all vehicle journeys for these vehicles
            for vehicle_id in vehicle_map.keys():
                try:
                    journeys = list(client.iter_results("vehiclejourneys", params={"vehicle": vehicle_id}))
                    
                    # Get unique trip IDs
                    trip_ids = set()
                    for journey in journeys:
                        if journey is None:
                            continue
                        trip_id = journey.get("trip_id")
                        if trip_id:
                            trip_ids.add(trip_id)
                    
                    # Fetch trips to get blocks
                    for trip_id in trip_ids:
                        try:
                            trips = list(client.iter_results("trips", params={"id": trip_id}))
                            for trip in trips:
                                if trip is None:
                                    continue
                                block = trip.get("block")
                                if block:
                                    vehicle_map[vehicle_id]["blocks"].add(block)
                        except Exception:
                            pass
                            
                except Exception:
                    # If we can't get journeys, mark as unable to fetch
                    vehicle_map[vehicle_id]["blocks"] = {"Unable to fetch blocks"}
            
            # Convert to list and sort blocks
            for vehicle_id, data in vehicle_map.items():
                if isinstance(data["blocks"], set):
                    data["blocks"] = sorted(data["blocks"]) if data["blocks"] else ["No block"]
                vehicles_data.append(data)
                
        except Exception as e:
            vehicles_data = [{"error": f"Error fetching data: {str(e)}"}]
    
    context = {
        "vehicles": vehicles_data,
        "operator_id": operator_id,
        "garage_id": garage_id,
    }
    
    return render(request, "tools/block_view.html", context)
