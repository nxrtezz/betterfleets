# UK National Rail Stations and Live Train Departures

This document describes the implementation of UK National Rail stations and live train departures support in BetterFleet.

## Overview

The system now supports:
- Importing UK railway stations as stop points with CRS codes from Transport Statistics API
- Train departure boards using the Transport Statistics API
- Automatic detection of train stations and display of train-specific departure information
- Future-proof architecture for adding other transport modes (tram, metro, ferry, coach)

## Database Changes

### StopPoint Model

Added a new field to the `StopPoint` model:

- `crs_code` (CharField, max_length=3, nullable, indexed): The 3-letter CRS code for railway stations (e.g., "SOT" for Stoke-On-Trent)

Migration: `busstops/migrations/0059_stoppoint_crs_code.py`

## Railway Station Import

### Management Command

A management command is available to import railway stations:

```bash
python manage.py import_railway_stations
```

#### Options

- `--file`: Path to a JSON or CSV file containing station data (alternative to API)
- `--url`: URL to fetch station data from (alternative to Transport Statistics API)
- `--update`: Update existing stations instead of skipping them
- `--dry-run`: Show what would be imported without making changes
- `--limit`: Limit number of stations to import (for testing)
- `--crs`: Import specific station by CRS code

#### Default Behavior (Transport Statistics API)

By default, the command fetches railway stations from the Transport Statistics API:

```
https://transportstatistics.com/api/stops/?active=true&crs=&atco_code=&naptan_code=&tiploc=
```

The API returns paginated results with all UK stops. The command filters for:
- Active stops only
- Stop type "RLS" (Rail Stations)
- Stops with CRS codes

The command handles pagination automatically to fetch all railway stations.

#### Alternative Data Sources

You can also import from a file or custom URL:

**JSON format:**
```json
[
  {
    "name": "London Waterloo",
    "crs": "WAT",
    "lat": 51.5031,
    "lon": -0.1132
  }
]
```

**CSV format:** Columns should include `name`, `crs`, `lat`, `lon` (or `latitude`, `longitude`).

#### Stop Type

Imported stations are assigned:
- `stop_type`: "RSE" (Rail station entrance)
- `atco_code`: Uses ATCO code from API if available, otherwise generated as "9{CRS}"
- `admin_area`: Set to "National Rail" (ID 999)

#### Examples

Import all railway stations from Transport Statistics API:
```bash
python manage.py import_railway_stations
```

Import with dry-run to preview:
```bash
python manage.py import_railway_stations --dry-run
```

Import specific station by CRS code:
```bash
python manage.py import_railway_stations --crs SOT
```

Import with limit for testing:
```bash
python manage.py import_railway_stations --limit 10
```

Import from local file:
```bash
python manage.py import_railway_stations --file stations.json
```

## Live Train Departures

### API Integration

The system fetches train departures from the Transport Statistics API:

```
https://transportstatistics.com/api/train-departures/?crs={CRS}
```

Example:
```
https://transportstatistics.com/api/train-departures/?crs=SOT
```

### Departure Provider

A new `TrainDepartures` class in `departures/sources.py` handles train departure fetching:

- Inherits from `RemoteDepartures` for consistent error handling and caching
- Caches responses for 30 seconds to avoid excessive API calls
- Gracefully handles API outages, invalid CRS codes, and empty responses
- Implements "poorly" state to back off during API issues

### Response Format

The API returns departure data in this format:

```json
{
    "date": "2026-06-14",
    "time_after": 63343,
    "station": {
        "name": "Stoke-On-Trent",
        "crs": "SOT",
        "tiploc": "STOKEOT",
        "lat": 53.0079887,
        "lon": -2.1810781,
        "link": "http://transportstatistics.com/api/departures/?crs=SOT"
    },
    "results": [
        {
            "time": {
                "from_date": "2026-05-17",
                "to_date": "2026-12-06",
                "arrival": "17:42:30",
                "departure": "17:44:00",
                "pass": null,
                "display": "17:42 - 17:44 | arr-dep",
                "sort_time": "17:44:00",
                "type": "stopping"
            },
            "platform": "1",
            "origin": {
                "name": "Manchester Piccadilly",
                "crs": "MAN",
                "tiploc": "MNCRPIC",
                "lat": 53.4772197,
                "lon": -2.2301402
            },
            "destination": {
                "name": "Bristol Temple Meads",
                "crs": "BRI",
                "tiploc": "BRSTLTM",
                "lat": 51.4490991,
                "lon": -2.5804029
            },
            "cif_train_uid": "W29907",
            "headcode": "1V65",
            "operator": "Cross County",
            "schedule_days_runs": "Sunday",
            "rtt_link": "https://www.realtimetrains.co.uk/service/gb-nr:W29907/2026-06-14/detailed",
            "pathed_as": "220, 221"
        }
    ]
}
```

**Note:** This API returns scheduled timetable data, not real-time live departures. The response includes departure times, platforms, origins, destinations, and service information.

## Departure Board UI

### Template

A dedicated train departure board template is used for train stations:

`busstops/templates/train_departures.html`

### Displayed Information

The departure board shows:
- Destination
- Origin
- Service ID / headcode
- Train operator
- Scheduled departure time
- Platform (highlighted when available)
- Service type (e.g., "stopping")

### Visual Indicators

- **Platform information**: Highlighted in blue when available
- **Responsive design**: Hides less critical columns (origin, operator) on mobile devices

## Integration

### Automatic Detection

The system automatically detects train stations in `get_departures_context()`:

```python
is_train_station = bool(stop.crs_code) and stop.stop_type in ["RSE", "RLY", "RPL"]
```

When a train station is detected:
- The `TrainDepartures` provider is used instead of bus departure logic
- The train-specific departure board template is rendered
- The context includes `is_train_station: True`

### Template Integration

The stop point detail template (`busstops/templates/busstops/stoppoint_detail.html`) conditionally includes:

- `train_departures.html` for train stations
- `departures.html` for bus stops

## Admin Support

### StopPoint Admin

The admin interface for `StopPoint` now includes:

- `crs_code` in the list display
- `crs_code` in search fields (can search by CRS code)
- Existing filters by `stop_type` can be used to find rail stations

### Managing Railway Stations

To manage railway stations in the admin:

1. Go to Django admin
2. Navigate to Bus stops → Stop points
3. Filter by `stop_type` = "Rail station entrance" (RSE)
4. Search by CRS code if needed
5. Edit station details including CRS code

## Caching and Error Handling

### Caching

- Train departure responses are cached for 30 seconds
- Cache key: `TrainDepartures:{stop_pk}`
- Reduces API load and improves response times

### Error Handling

The system handles various error conditions:

- **API timeouts**: Back off for 1 minute
- **API errors**: Back off for 30 minutes
- **Invalid CRS codes (404)**: Return empty departures, don't mark as poorly
- **Invalid responses**: Back off for 5 minutes
- **Missing CRS code**: Return empty departures gracefully

### Poorly State

The "poorly" state mechanism prevents hammering failing APIs:
- Key: `train_departures:{crs_code}`
- Automatically backs off when errors occur
- Recovers after timeout period

## Future-Proofing

The architecture is designed to support additional transport modes:

### Extending to Other Modes

To add support for trams, metros, ferries, or coaches:

1. Add appropriate fields to `StopPoint` model (if needed)
2. Create a new departure provider class inheriting from `RemoteDepartures`
3. Implement the required methods:
   - `get_request_url()`
   - `get_request_params()`
   - `get_request_headers()`
   - `get_row()` to parse API responses
   - `get_poorly_key()` for error handling
4. Update `get_departures_context()` to detect the new mode
5. Create a mode-specific departure template
6. Update the stop point template to include the new template

### Example: Adding Tram Support

```python
class TramDepartures(RemoteDepartures):
    def __init__(self, stop):
        super().__init__(stop, [])
        self.tram_code = stop.tram_code  # Add tram_code field to StopPoint
    
    def get_request_url(self):
        return "https://api.example.com/tram/departures"
    
    # ... implement other methods
```

## Refreshing Station Data

### Manual Refresh

To refresh railway station data from Transport Statistics API:

```bash
python manage.py import_railway_stations --update
```

To refresh from a file:

```bash
python manage.py import_railway_stations --file /path/to/stations.json --update
```

### Automated Refresh

Set up a scheduled task (cron, systemd timer, etc.) to periodically refresh station data:

```bash
# Example cron job (daily at 3 AM)
0 3 * * * cd /path/to/betterfleet && python manage.py import_railway_stations --update
```

## Configuration

### Environment Variables

No specific environment variables are required for the basic implementation. The Transport Statistics API URLs are hardcoded in the respective classes.

To customize the API URLs, modify the relevant files:

**Train departures URL** (`departures/sources.py`):
```python
def get_request_url(self) -> str:
    return settings.TRAIN_DEPARTURES_URL  # Add to settings.py
```

**Stations API URL** (`busstops/management/commands/import_railway_stations.py`):
```python
base_url = settings.STATIONS_API_URL  # Add to settings.py
```

### Settings

Add to `settings.py` if needed:

```python
# Train departures configuration
TRAIN_DEPARTURES_URL = "https://transportstatistics.com/api/train-departures/"
STATIONS_API_URL = "https://transportstatistics.com/api/stops/"
TRAIN_DEPARTURES_CACHE_TIMEOUT = 30  # seconds
TRAIN_DEPARTURES_TIMEOUT = 5  # API request timeout
```

## Troubleshooting

### No Departures Showing

1. Check the station has a valid CRS code
2. Verify the stop_type is set to "RSE", "RLY", or "RPL"
3. Check browser console for JavaScript errors
4. Verify the Transport Statistics API is accessible
5. Check Django logs for API errors

### API Errors

1. Check network connectivity
2. Verify the API URL is correct
3. Check if the API is experiencing outages
4. Review "poorly" state in cache: `cache.get("train_departures:{crs_code}")`

### Import Issues

1. Verify data file format (JSON or CSV) if using file import
2. Check required fields are present (name, crs, lat, lon)
3. Use `--dry-run` to preview changes
4. Check Django logs for import errors
5. Verify Transport Statistics API is accessible if using default import

## Performance Considerations

- Caching reduces API calls to once per 30 seconds per station
- Database indexes on `crs_code` for efficient lookups
- Lazy loading of departure data (only fetched when viewing a station)
- "Poorly" state prevents hammering failing APIs
- Pagination in station import to handle large datasets efficiently

## Security Considerations

- CRS codes are public identifiers
- No authentication required for Transport Statistics API
- Input validation on CRS codes (max 3 characters)
- SQL injection protection via Django ORM

## Testing

### Manual Testing

1. Import sample stations with dry-run:
   ```bash
   python manage.py import_railway_stations --dry-run --limit 5
   ```

2. Apply migration:
   ```bash
   python manage.py migrate busstops
   ```

3. Import stations for real:
   ```bash
   python manage.py import_railway_stations --limit 10
   ```

4. Visit a station page in the browser to see departures

### Unit Tests

Create tests for:
- Railway station import command
- TrainDepartures provider
- Departure context logic
- Template rendering

## Maintenance

Regular maintenance tasks:

- Monitor API performance and error rates
- Update station data periodically (monthly recommended)
- Review and update API endpoints if they change
- Check cache hit rates and adjust timeout if needed
- Monitor "poorly" state frequency

## Support

For issues or questions:
- Check Django logs for detailed error messages
- Review the Transport Statistics API documentation
- Test with `--dry-run` and `--limit` options first
- Use `--crs` to test with specific stations
