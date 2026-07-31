# Vehicle History Timeline System

## Overview

The Vehicle History Timeline System provides a human-readable timeline layer for tracking notable events that happen to vehicles. This system operates alongside existing audit/history mechanisms without replacing or interfering with them.

### System Relationships

- **VehicleSnapshot**: Historical state of a vehicle at a point in time
- **Revision system**: Auditing who changed data and when
- **VehicleHistoryEvent**: Notable events that happened (or will happen) to a vehicle

The Vehicle History system is a human-readable timeline layer that complements the existing systems.

## Architecture

### Models

#### VehicleHistoryEvent

The core model representing a single event in a vehicle's timeline.

**Fields:**
- `vehicle`: ForeignKey to Vehicle
- `event_type`: CharField with predefined choices (see Event Types below)
- `title`: CharField(max_length=255) - Human-readable event title
- `description`: TextField(blank=True) - Optional detailed description
- `event_date`: DateField(null=True, blank=True) - When the event occurred
- `date_precision`: CharField with choices (DAY, MONTH, YEAR, UNKNOWN)
- `is_future_event`: BooleanField(default=False) - Mark planned future events
- `is_automatic`: BooleanField(default=False) - Auto-generated from vehicle changes
- `created_by`: ForeignKey to User (nullable) - Who created the event
- `metadata`: JSONField(default=dict) - Structured event data
- `created_at`: DateTimeField(auto_now_add=True)
- `updated_at`: DateTimeField(auto_now=True)

**Indexes:**
- Single indexes on: vehicle, event_type, event_date, is_future_event, created_at
- Compound indexes: (vehicle, event_date), (vehicle, event_type)

#### VehicleHistoryAttachment

Supporting model for attaching photographs and evidence to events.

**Fields:**
- `event`: ForeignKey to VehicleHistoryEvent
- `photo`: ForeignKey to Photo
- `caption`: CharField(max_length=255, blank=True)

### Event Types

The system supports the following hard-coded event types:

| Event Type | Description |
|------------|-------------|
| TRANSFER | Vehicle transferred between operators |
| REPAINT | Vehicle repainted or livery changed |
| RENUMBERED | Fleet number changed |
| REGISTRATION_CHANGE | Registration plate changed |
| NAME_APPLIED | Vehicle name added |
| NAME_REMOVED | Vehicle name removed |
| BRANDING_APPLIED | Branding added |
| BRANDING_REMOVED | Branding removed |
| GARAGE_TRANSFER | Vehicle transferred between garages |
| ENTERED_SERVICE | Vehicle entered service |
| WITHDRAWN | Vehicle withdrawn from service |
| REINSTATED | Vehicle returned to service |
| PRESERVED | Vehicle preserved |
| SCRAPPED | Vehicle scrapped |
| SOLD | Vehicle sold |
| DELIVERED | Vehicle delivered |
| FEATURE_ADDED | Feature added to vehicle |
| FEATURE_REMOVED | Feature removed from vehicle |
| VOR | Vehicle off road |
| RETURNED_TO_SERVICE | Vehicle returned to service |
| OTHER | Other events |

## Automatic Event Generation

The system automatically generates VehicleHistoryEvents when certain vehicle fields change. This is implemented via Django signals.

### Tracked Fields

The following field changes trigger automatic event generation:

- `operator` → TRANSFER event
- `livery` → REPAINT event
- `garage` → GARAGE_TRANSFER event
- `reg` → REGISTRATION_CHANGE event
- `name` → NAME_APPLIED or NAME_REMOVED event
- `branding` → BRANDING_APPLIED or BRANDING_REMOVED event
- `withdrawn` → WITHDRAWN or REINSTATED event
- `preserved` → PRESERVED event
- `vor` → VOR or RETURNED_TO_SERVICE event

### Event Titles

Automatic events use descriptive titles based on the change:

**Operator change:**
- `Transferred from Stagecoach South to Stagecoach East`
- `Added to Stagecoach South`
- `Removed from Stagecoach South`

**Livery change:**
- `Repainted into Beachbus Livery`
- `Painted into Beachbus Livery`
- `Removed Beachbus Livery`

**Garage change:**
- `Transferred from Worthing Depot to Chichester Depot`
- `Assigned to Worthing Depot`
- `Removed from Worthing Depot`

**Registration change:**
- `Registration changed from AB12 CDE to XY34 ZZZ`
- `Registration set to XY34 ZZZ`
- `Registration AB12 CDE removed`

### Duplicate Prevention

The system checks for recent automatic events with the same vehicle, event type, and title before creating a new event to prevent duplicates.

## Metadata Format

Events use the `metadata` JSONField to store structured references to related entities.

### Transfer Event

```json
{
  "from_operator": 12,
  "to_operator": 15
}
```

### Repaint Event

```json
{
  "from_livery": 3,
  "to_livery": 8
}
```

### Garage Transfer Event

```json
{
  "from_garage": 2,
  "to_garage": 5
}
```

### Registration Change Event

```json
{
  "from_registration": "AB12 CDE",
  "to_registration": "XY34 ZZZ"
}
```

### Name Change Event

```json
{
  "from_name": "Old Name",
  "to_name": "New Name"
}
```

### Branding Change Event

```json
{
  "from_branding": "Old Branding",
  "to_branding": "New Branding"
}
```

The API serializer resolves these references into display data, including entity names and identifiers.

## API Endpoints

### Vehicle Timeline

**Endpoint:** `/api/vehicle-history/vehicle/{vehicle_id}/timeline/`

**Method:** GET

**Description:** Returns the complete event history for a specific vehicle, including future events and attachments.

**Query Parameters:**
- `event_type` (optional): Filter by event type
- `year` (optional): Filter by year (integer)
- `future_only` (optional): If true, only return future events
- `automatic_only` (optional): If true, only return automatic events

**Response:**
```json
{
  "vehicle": {
    "id": 123,
    "slug": "stagecoach-south-12345",
    "fleet_code": "12345",
    "reg": "AB12 CDE",
    "name": "12345 - AB12 CDE",
    "operator": {
      "id": 12,
      "name": "Stagecoach South",
      "slug": "stagecoach-south"
    }
  },
  "events": [
    {
      "id": 1,
      "vehicle": {...},
      "event_type": "transfer",
      "event_type_display": "Transfer",
      "title": "Transferred from Stagecoach South to Stagecoach East",
      "description": "",
      "event_date": "2024-01-15",
      "date_precision": "day",
      "date_precision_display": "Day",
      "is_future_event": false,
      "is_automatic": true,
      "created_by": {...},
      "metadata": {
        "from_operator": 12,
        "to_operator": 15
      },
      "metadata_resolved": {
        "from_operator": {
          "id": 12,
          "name": "Stagecoach South",
          "slug": "stagecoach-south"
        },
        "to_operator": {
          "id": 15,
          "name": "Stagecoach East",
          "slug": "stagecoach-east"
        }
      },
      "attachments": [],
      "created_at": "2024-01-15T10:30:00Z",
      "updated_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### Operator Timeline

**Endpoint:** `/api/vehicle-history/operator/{operator_id}/timeline/`

**Method:** GET

**Description:** Returns all VehicleHistoryEvents involving vehicles belonging to the operator.

**Query Parameters:**
- `event_type` (optional): Filter by event type
- `year` (optional): Filter by year (integer)
- `vehicle` (optional): Filter by specific vehicle ID
- `future_only` (optional): If true, only return future events
- `automatic_only` (optional): If true, only return automatic events

**Response:**
```json
{
  "operator": {
    "id": 12,
    "noc": "SCSU",
    "name": "Stagecoach South",
    "slug": "stagecoach-south"
  },
  "events": [...]
}
```

### Vehicle History Event CRUD

**Endpoint:** `/api/vehicle-history/`

**Methods:**
- GET: List all history events (with filtering)
- POST: Create a new history event
- PUT/PATCH: Update an existing history event
- DELETE: Delete a history event

**Permissions:**
- Read access: Matches existing vehicle visibility rules
- Write access: Authenticated users with vehicle edit permissions

## Timeline Ordering

Timeline events are ordered by:
1. `event_date` descending (most recent first)
2. `created_at` descending (for events with the same date)

Future events (where `is_future_event=true`) appear in the timeline and are clearly marked.

## Django Admin

The system includes comprehensive Django admin support:

**VehicleHistoryEvent Admin:**
- List display: vehicle, event_type, title, event_date, date_precision, is_future_event, is_automatic, created_by, created_at
- Filters: event_type, date_precision, is_future_event, is_automatic, event_date, created_at
- Search: vehicle code/reg/fleet_code, title, description, created_by username
- Date hierarchy: event_date
- Fieldsets: Basic Information, Date Information, Event Details, Timestamps

**VehicleHistoryAttachment Admin:**
- List display: event, photo, caption
- Filters: event_type
- Search: event title, vehicle code/reg, caption

## Future Extension Points

The system is designed to support future enhancements:

### Historical Imports

The metadata structure and date precision fields support importing historical data from fleet databases where exact dates may not be known.

### Additional Event Types

New event types can be added to the `EventType` choices without breaking existing data.

### Custom Metadata Schemas

Different event types can have custom metadata schemas while maintaining a consistent API through the `metadata_resolved` serializer field.

### Attachment Expansion

The `VehicleHistoryAttachment` model can be extended to support additional attachment types (documents, videos, etc.) beyond photographs.

## Permissions

### API Permissions

- **Read access**: Matches existing vehicle visibility rules
- **Create/Edit/Delete**: Requires authentication and vehicle edit permissions

### Admin Permissions

- Standard Django admin permissions apply
- Users with `vehicle_history.add_vehiclehistoryevent` can create events
- Users with `vehicle_history.change_vehiclehistoryevent` can edit events
- Users with `vehicle_history.delete_vehiclehistoryevent` can delete events

## Testing

The system includes comprehensive tests covering:

- Event creation, editing, and deletion
- Automatic transfer events
- Automatic repaint events
- Future events handling
- Operator timeline endpoint
- Vehicle timeline endpoint
- Attachment handling
- Duplicate prevention
- Metadata resolution

Run tests with:
```bash
python manage.py test vehicle_history
```

## Integration Notes

### App Configuration

Add to `INSTALLED_APPS`:
```python
INSTALLED_APPS = [
    ...
    'vehicle_history',
]
```

### Signal Registration

The app's `signals.py` module is automatically loaded when the app is ready. No additional configuration is required.

### API Router Registration

Add to your DRF router configuration:
```python
from rest_framework import routers
from vehicle_history.views import VehicleHistoryEventViewSet

router = routers.DefaultRouter()
router.register(r'vehicle-history', VehicleHistoryEventViewSet, basename='vehicle-history')
```

## Important Constraints

1. **Do NOT modify or replace the existing revision system** - The history system operates alongside existing audit mechanisms
2. **Do NOT modify or replace VehicleSnapshot functionality** - VehicleSnapshot continues to serve its purpose
3. **Keep implementation modular and reusable** - Design for future support of historical imports
4. **Design for future extension** - The metadata structure supports custom schemas per event type
