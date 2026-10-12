# GTFS Designer Setup Guide

## What Has Been Built

A complete GTFS timetable creator tool for BetterFleets with the following components:

### 1. Django App Structure
- **gtfsdesigner/** - Main app directory
  - **models.py** - Complete GTFS data models (Project, Operator, Route, Calendar, Stop, Trip, etc.)
  - **views.py** - All view functions with superuser protection
  - **urls.py** - URL routing for all pages and API endpoints
  - **export.py** - GTFS ZIP export functionality
  - **admin.py** - Django admin integration
  - **templates/gtfsdesigner/** - All HTML templates with custom styling

### 2. Features Implemented

#### Project Management
- Create and list GTFS projects
- Project-scoped data (operators, routes, stops, calendars, trips)

#### Operator Creation
- Full GTFS agency fields: name, NOC, URL, timezone, language, phone, email, fare URL
- Linked to projects

#### Route Management
- Route ID, short name, long name, description
- Route type (bus, tram, rail, ferry, etc.)
- Route colors and URL
- Linked to operators

#### Stop Selection
- Search existing BetterFleets stops (via API)
- Add new custom stops
- Interactive Leaflet map integration
- Visual route path display (inbound = blue dashed, outbound = green)
- Separate inbound/outbound selection
- Click stops to show on map
- Add stops by clicking on map

#### Calendar Configuration
- Weekly schedule (Mon-Sun checkboxes)
- Start and end dates
- Service ID configuration
- Exception dates support (via calendar_dates model)

#### Timetable Builder
- Spreadsheet-like interface
- Day selector (weekday, Saturday, Sunday, custom date)
- Add/delete trips
- Time input for each stop
- Stop settings modal:
  - Timing point toggle
  - Pickup only toggle
  - Drop-off only toggle
- Copy timetable from another day
- Visual indicators for special stops

#### GTFS Export
- Generates all required GTFS files:
  - agency.txt
  - stops.txt
  - routes.txt
  - trips.txt
  - stop_times.txt
  - calendar.txt
  - calendar_dates.txt
- Downloads as ZIP file

### 3. Security
- All views protected with `@login_required` and `@superuser_required`
- Custom decorator for superuser access
- Projects scoped to creating user
- CSRF protection on all forms

### 4. Custom Styling
- Completely separate from BetterFleets default design
- Clean, modern interface
- Responsive layout
- Color-coded features (timing points, pickup/drop-off only)
- Interactive map with path visualization

## Installation Steps

### 1. The app is already registered
The gtfsdesigner app has been added to `INSTALLED_APPS` in `buses/settings.py`

### 2. The URL is already configured
The gtfsdesigner URLs have been added to `buses/urls.py` at `/gtfsdesigner/`

### 3. Run migrations (when database is available)
```bash
python manage.py makemigrations gtfsdesigner
python manage.py migrate
```

### 4. Access the tool
Navigate to: `http://localhost:8000/gtfsdesigner/`

**Note**: Requires superuser access to view and use the tool.

## Usage Workflow

1. **Login as superuser**
2. **Navigate to /gtfsdesigner/**
3. **Create a project** - Give it a name (e.g., "London Bus Network 2027")
4. **Add operator** - Enter operator details (name, NOC, contact info)
5. **Create route** - Define route with service number and description
6. **Select stops**:
   - Search for existing stops or add new ones
   - Select inbound stops (order matters)
   - Select outbound stops (inbound path shown as guide)
   - Click stops on map to verify locations
7. **Configure calendar**:
   - Select days of operation
   - Set start and end dates
   - Define service ID
8. **Build timetable**:
   - Select route and calendar
   - Choose a day or custom date
   - Add trips and set times
   - Configure timing points and pickup/drop-off restrictions
   - Copy from another day if needed
   - Save timetable
9. **Export GTFS** - Download the complete GTFS ZIP file

## API Endpoints

### Search Stops
```
GET /gtfsdesigner/api/stops/search/?q=query
```
Returns JSON with matching stops from BetterFleets database.

### Create Stop
```
POST /gtfsdesigner/api/stops/create/
```
Creates a new custom stop in the GTFS project.

### Save Stops
```
POST /gtfsdesigner/project/<id>/stops/save/
```
Saves selected stops for a route with direction.

### Save Timetable
```
POST /gtfsdesigner/project/<id>/timetable/save/
```
Saves timetable data (trips and times).

## Database Models

### Core Models
- **GTFSProject** - Project container
- **GTFSOperator** - GTFS agency
- **GTFSRoute** - GTFS route
- **GTFSCalendar** - Weekly service pattern
- **GTFSCalendarDate** - Exception dates
- **GTFSStop** - Stop definition (can reference existing StopPoint)
- **GFSTrip** - Trip definition
- **GFSTripStop** - Trip-stop relationship with sequence and settings
- **GFSTripTiming** - Timing information for each stop in a trip

## Files Structure

```
gtfsdesigner/
├── __init__.py
├── admin.py              # Django admin configuration
├── apps.py               # App configuration
├── export.py             # GTFS export functionality
├── migrations/
│   └── __init__.py
├── models.py             # Database models
├── templates/
│   └── gtfsdesigner/
│       ├── base.html             # Base template with custom styling
│       ├── index.html           # Project list
│       ├── create_project.html  # Create project form
│       ├── project_detail.html  # Project overview with progress
│       ├── create_operator.html # Create operator form
│       ├── create_route.html    # Create route form
│       ├── create_calendar.html # Create calendar form
│       ├── select_stops.html    # Stop selection with map
│       └── timetable_builder.html # Spreadsheet timetable editor
├── urls.py               # URL routing
├── views.py              # View functions
├── README.md             # Documentation
└── SETUP.md              # This file
```

## Known Limitations / TODO

1. **Stop-Route Association**: The current implementation has placeholders for saving stops to routes. A RouteStop model would be needed to properly link stops to routes with direction information.

2. **Timetable Persistence**: The save_timetable view has a placeholder. Full implementation would need to:
   - Create GFSTrip records
   - Create GFSTripStop records with sequence
   - Create GFSTripTiming records with times
   - Handle timing point and pickup/drop-off settings

3. **Shape Files**: GTFS shapes.txt is not generated. This would require:
   - Storing route geometry
   - Generating shape points from stop coordinates
   - Adding shape_id to trips

4. **Calendar Dates UI**: The calendar_dates model exists but there's no UI for adding exception dates.

5. **Validation**: No GTFS specification validation is performed. Consider adding a validator before export.

6. **Import**: No GTFS import functionality exists (only export).

## Testing Recommendations

1. Test superuser access control
2. Test the complete workflow from project creation to export
3. Verify GTFS export produces valid files
4. Test with real BetterFleets stop data
5. Test map functionality with various browsers
6. Test form validation
7. Test that users without superuser access are denied

## Browser Requirements

- Modern browser with ES6+ support
- JavaScript enabled
- Internet connection for map tiles (Leaflet uses OpenStreetMap)

## Support

For issues or questions:
1. Check the README.md for detailed feature documentation
2. Review the GTFS specification at https://gtfs.org/documentation/schedule/reference/
3. Ensure database migrations have been run
4. Verify superuser permissions
