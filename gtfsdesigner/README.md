# GTFS Designer

A web-based tool for creating GTFS (General Transit Feed Specification) data for BetterFleets. This tool allows superusers to create complete GTFS datasets through an intuitive interface.

## Features

- **Project Management**: Create and manage multiple GTFS projects
- **Operator Creation**: Define transit operators/agencies with all GTFS-compliant fields
- **Route Management**: Create routes with full GTFS support (route types, colors, descriptions)
- **Stop Selection**: 
  - Select from existing BetterFleets stops
  - Add new custom stops
  - Interactive map integration with Leaflet
  - Visual route path display
  - Separate inbound/outbound stop selection
- **Calendar Configuration**: 
  - Weekly schedule patterns (Mon-Sun)
  - Date ranges with start/end dates
  - Exception dates (added/removed services)
- **Timetable Builder**:
  - Spreadsheet-like interface
  - Timing point configuration
  - Pickup/drop-off only settings
  - Copy timetables between days
  - Day-specific or date-specific scheduling
- **GTFS Export**: Export complete GTFS ZIP files with all required files

## GTFS Files Generated

The tool generates the following GTFS files:
- `agency.txt` - Operator/agency information
- `stops.txt` - Stop locations and details
- `routes.txt` - Route definitions
- `trips.txt` - Trip definitions
- `stop_times.txt` - Stop timing information
- `calendar.txt` - Weekly service patterns
- `calendar_dates.txt` - Exception dates

## Installation

1. The gtfsdesigner app is already added to `INSTALLED_APPS` in `buses/settings.py`
2. Run migrations:
   ```bash
   python manage.py makemigrations gtfsdesigner
   python manage.py migrate
   ```

## Usage

### Access

The GTFS Designer is accessible at `/gtfsdesigner/` and requires superuser access.

### Workflow

1. **Create a Project**: Give your GTFS project a name
2. **Add Operator**: Define the transit operator (agency) with NOC, name, contact details
3. **Create Route**: Add routes with service number, description, and route type
4. **Select Stops**: 
   - Choose inbound stops from existing stops or create new ones
   - Select outbound stops (inbound path shown as guide)
   - Click stops on map to see their location
5. **Configure Calendar**: Set service days (Mon-Sun) and date ranges
6. **Build Timetable**:
   - Select a day or specific date
   - Add trips and set departure/arrival times
   - Configure timing points and pickup/drop-off restrictions
   - Copy timetable from another day
7. **Export GTFS**: Download the complete GTFS ZIP file

## API Endpoints

- `GET /gtfsdesigner/api/stops/search/?q=query` - Search existing stops
- `POST /gtfsdesigner/api/stops/create/` - Create a new stop

## Data Model

### GTFSProject
- Main project container
- Links to operators, routes, stops, calendars, trips

### GTFSOperator
- GTFS agency/operator
- Fields: name, noc, url, timezone, lang, phone, email, fare_url

### GTFSRoute
- GTFS route
- Fields: route_id, route_short_name, route_long_name, route_desc, route_type, route_color, etc.

### GTFSCalendar
- Weekly service pattern
- Fields: service_id, mon-sun booleans, start_date, end_date

### GTFSCalendarDate
- Exception dates
- Fields: service_id, date, exception_type (1=added, 2=removed)

### GTFSStop
- Stop definition
- Can reference existing StopPoint or be new
- Fields: stop_id, stop_name, stop_lat, stop_lon, location_type, etc.

### GFSTrip
- Trip definition
- Fields: trip_id, trip_headsign, direction_id, service_id, etc.

### GFSTripStop
- Intermediate model for trip stops
- Fields: sequence, is_timing_point, pickup_type, drop_off_type

### GFSTripTiming
- Timing information for each stop in a trip
- Fields: arrival_time, departure_time, stop_headsign, etc.

## Security

- All views require `@login_required` and `@superuser_required` decorators
- Only superusers can access the GTFS Designer
- Projects are scoped to the creating user

## Custom Styling

The GTFS Designer uses its own custom styling (separate from BetterFleets default design) as requested. All styles are inline in the base template to ensure complete visual separation.

## Browser Compatibility

- Modern browsers (Chrome 90+, Firefox 88+, Safari 14+, Edge 90+)
- Requires JavaScript for map and interactive features
- Leaflet maps require internet connection for tile loading

## Future Enhancements

Potential improvements:
- Import existing GTFS files
- Shape file generation and visualization
- Fare configuration (fare_attributes.txt, fare_rules.txt)
- Transfer rules
- Multi-route projects
- Validation against GTFS specification
- Preview before export
- Save/load timetable templates
