# Implement Photographed Buses

This plan outlines the addition of "photographed buses" functionality as requested. This feature works similarly to "ridden buses" but tracks the number of times a bus has been photographed (quantity). It updates stats on user profiles, operator pages, and provides a REST API endpoint.

## Proposed Changes

---

### Fleet App (Models & Utils)

#### [MODIFY] [fleet/models.py](file:///z:/betterfleets/betterfleet/fleet/models.py)
- **FleetPhotoLog**: Add `quantity = models.PositiveIntegerField(default=1)` field to the `FleetPhotoLog` model. 

#### [MODIFY] [fleet/completion.py](file:///z:/betterfleets/betterfleet/fleet/completion.py)
- **Stats calculation**: Ensure `get_user_photo_stats` and other photo log aggregation functions sum the `quantity` instead of just counting rows.

---

### Vehicles App (UI & Views)

#### [MODIFY] [vehicles/views.py](file:///z:/betterfleets/betterfleet/vehicles/views.py)
- **VehicleDetailView (get_context_data)**: Add context variables `can_photo_log` and `photo_log_quantity` to check if a user has photographed the vehicle and retrieve the quantity.
- **VehicleDetailView (post)**: Add handling for `photo_quantity` input from the form, updating or deleting the `FleetPhotoLog` depending on whether the quantity is `0` or greater.

#### [MODIFY] [vehicles/templates/vehicles/vehicle_detail.html](file:///z:/betterfleets/betterfleet/vehicles/templates/vehicles/vehicle_detail.html)
- Add a new form near the "Log vehicle" button, allowing users to input and submit the number of times they've photographed the bus.

---

### Accounts & Busstops Apps (Stats Display)

#### [MODIFY] [accounts/templates/user_detail.html](file:///z:/betterfleets/betterfleet/accounts/templates/user_detail.html)
- Add "photographed" stat next to the "ridden" stat on the user profile page.

#### [MODIFY] [busstops/templates/operator_vehicles.html](file:///z:/betterfleets/betterfleet/busstops/templates/operator_vehicles.html)
- Ensure the operator's vehicle list displays the "Photographed" count column alongside the "Ridden" column, as requested. Update context generation in the view if necessary.

---

### API App

#### [NEW/MODIFY] [api/views.py](file:///z:/betterfleets/betterfleet/api/views.py)
- Add a new viewset/endpoint (e.g., `LogPhotoViewSet` or an action) for logging photos via POST request.
- Endpoint should take `reg`, `operator_noc`, and optionally `quantity` (default 1).
- Authenticate requests using `IsAPIKeyAuthenticated`.
- Create or update the `FleetPhotoLog` for the authenticated user and matching vehicle.

#### [MODIFY] [api/urls.py](file:///z:/betterfleets/betterfleet/api/urls.py)
- Register the new photo logging endpoint.

## Verification Plan

### Manual Verification
- View a vehicle detail page, add a photograph log with a specific quantity, verify it saves and updates the UI.
- Verify user profile and operator vehicle list show correct photograph quantity.
- Send a `POST` request with a valid API key, `reg`, and `operator_noc` to the new endpoint and verify it updates the `FleetPhotoLog` quantity successfully in the database.
