# GTFS Rail Import Documentation

This document describes the UK National Rail GTFS import system for BetterFleet.

## Overview

The `import_gtfs_services` management command imports UK National Rail GTFS data and automatically populates service definitions and timetable data with intelligent deduplication.

## GTFS Files Used

The importer reads the following GTFS files:

- **agency.txt** - Operator/agency information
- **routes.txt** - Route definitions
- **trips.txt** - Individual journey definitions
- **stop_times.txt** - Detailed stop timing information
- **stops.txt** - Station/location information
- **calendar.txt** - Regular day-of-week service patterns
- **calendar_dates.txt** - Exception dates (added/removed services)

## Command Usage

```bash
python manage.py import_gtfs_services --gtfs-path /path/to/gtfs
```

### Options

- `--gtfs-path` (required) - Path to directory containing GTFS .txt files
- `--purge` - Remove previously imported rail services and rebuild from scratch

### Example

```bash
python manage.py import_gtfs_services --gtfs-path /data/national-rail-gtfs
```

With purge:

```bash
python manage.py import_gtfs_services --gtfs-path /data/national-rail-gtfs --purge
```

## Service Generation Logic

### Deduplication Strategy

Services are deduplicated based on a unique key comprising:

```
(operator_id, origin_crs, destination_crs)
```

This ensures that only one Service record exists for a given operator and route pair, regardless of how many trips are in the GTFS feed.

### Service Naming

**Line Name Format:**
```
{origin_crs} - {destination_crs}
```

Examples:
- `SOU - BTN` (Southampton Central to Brighton)
- `BTN - SOU` (Brighton to Southampton Central)
- `VIC - BTN` (London Victoria to Brighton)
- `KGX - EDB` (London King's Cross to Edinburgh)

**Description Format:**
```
{origin_name} - {destination_name}
```

Examples:
- `Southampton Central - Brighton`
- `Brighton - Southampton Central`
- `London Victoria - Brighton`
- `London King's Cross - Edinburgh`

### Operator Mapping

The importer:

1. Reads operator information from `agency.txt`
2. Attempts to match to existing Operator records by:
   - Exact name match (case-insensitive)
   - NOC code match (case-insensitive)
3. Creates new Operator records if no match is found
4. Sets `vehicle_mode` to "rail" for all rail operators

### Station Mapping

Stations are read from `stops.txt` and:

1. Mapped to StopPoint records with `atco_code` format: `rail-{stop_id}`
2. CRS codes are extracted from `stop_code` field
3. Station names are truncated to 48 characters (StopPoint field limit)
4. Stop type is set to "RPL" (Rail Platform)

## Timetable Generation Logic

### Trip Processing

For each trip in `trips.txt`:

1. **Origin Determination:** First stop in the trip's stop_times
2. **Destination Determination:** Last stop in the trip's stop_times
3. **Service Lookup:** Find or create Service based on (operator, origin_crs, destination_crs)
4. **Route Creation:** Create Route record linking to Service
5. **Trip Creation:** Create Trip record with:
   - Route reference
   - Calendar reference
   - Start time (departure from origin)
   - End time (arrival at destination)
   - Ticket machine code (trip_id)

### Calendar Processing

Calendars are read from `calendar.txt` and mapped to Calendar model fields:

- `monday` → `mon`
- `tuesday` → `tue`
- `wednesday` → `wed`
- `thursday` → `thu`
- `friday` → `fri`
- `saturday` → `sat`
- `sunday` → `sun`
- `start_date` → `start_date`
- `end_date` → `end_date`

Exception dates from `calendar_dates.txt` are stored for future use in more complex scheduling logic.

## Calling Pattern Import

### Stop Time Processing

For each trip, all stop times from `stop_times.txt` are imported as calling points:

1. **Stop Sequence:** Preserved from GTFS `stop_sequence` field
2. **Arrival Time:** Parsed from GTFS `arrival_time` field
3. **Departure Time:** Parsed from GTFS `departure_time` field
4. **Station:** Linked to StopPoint record
5. **Timing Status:** Set to default (could be enhanced with GTFS `timepoint` field)

### Example Calling Pattern

A trip from Southampton Central to Brighton might have:

```
1. Southampton Central (depart 06:14)
2. Woolston (depart 06:19)
3. Sholing (depart 06:22)
4. Netley (depart 06:26)
5. Hamble (depart 06:30)
6. Fareham (depart 06:38)
7. Portsmouth Harbour (depart 06:48)
8. Brighton (arrive 08:14)
```

Each of these becomes a StopTime record linked to the Trip.

## Performance Considerations

The importer is designed to handle large GTFS feeds efficiently:

### Bulk Operations

- **Stops:** Bulk create/update with batch size of 1000
- **Trips:** Bulk create with batch size of 1000
- **Stop Times:** Uses PostgreSQL COPY command for maximum performance

### Streaming

- CSV files are read line-by-line using Python's csv module
- No in-memory loading of entire datasets
- Dictionary lookups used for O(1) access to cached objects

### Memory Management

- Trip stop times are organized by trip_id using defaultdict
- Service deduplication uses dictionary for O(1) key lookup
- Large datasets are processed in batches

### Database Optimization

- Transactions used for atomic operations
- Indexes on Service.line_name, Operator.noc, etc. for fast lookups
- COPY command bypasses ORM overhead for StopTime insertion

## Data Relationships

The resulting data structure:

```
Operator (busstops.Operator)
 └─ Service (busstops.Service)
     ├─ Route (bustimes.Route)
     │   └─ Trip (bustimes.Trip)
     │       └─ StopTime (bustimes.StopTime) [Calling Points]
     └─ StopPoint (busstops.StopPoint) [via StopUsage]
```

### Example

```
Operator: Southern (noc: SOU)
 └─ Service: SOU - BTN
     ├─ Route: SOU-BTN-001
     │   ├─ Trip: 06:14 departure
     │   │   ├─ StopTime: Southampton Central (06:14)
     │   │   ├─ StopTime: Fareham (06:38)
     │   │   └─ StopTime: Brighton (08:14)
     │   ├─ Trip: 07:14 departure
     │   └─ Trip: 08:14 departure
     └─ Photos (future enhancement)
```

## Purge Functionality

The `--purge` option removes all previously imported rail data:

1. Deletes StopTime records for rail trips
2. Deletes Trip records for rail routes
3. Deletes Route records for rail source
4. Deletes Service records for rail source
5. Deletes the DataSource record

This is performed within a transaction to ensure atomicity.

## Progress Logging

The command provides detailed progress output:

```
Reading operators...
Found 15 operators
Reading stations...
Found 2500 stations
Reading trips...
Found 84321 trips
Reading stop_times...
Found 1942117 trip stop times
Reading calendars...
Found 450 calendars
Generating services...
Southern: 18 services
SWR: 27 services
LNER: 14 services
Services created: 412
Generating timetables...
Timetable entries created: 84,321
Generating calling patterns...
Calling points created: 1,942,117
Import complete.
```

## Re-running Imports

### Full Re-import

To completely refresh the data:

```bash
python manage.py import_gtfs_services --gtfs-path /data/gtfs --purge
```

### Incremental Update

To update without purging (may create duplicates if service keys change):

```bash
python manage.py import_gtfs_services --gtfs-path /data/gtfs
```

**Note:** The deduplication logic is based on (operator, origin_crs, destination_crs). If these values change in the GTFS feed, new services will be created rather than updating existing ones.

## GTFS as Source of Truth

The importer treats GTFS as the authoritative source:

- All scheduled trains are imported
- Service definitions are generated from trip data
- Calling patterns are preserved exactly as in GTFS
- No manual overrides during import

For manual adjustments, use the Django admin or separate management commands after import.

## Future Enhancements

Potential improvements:

1. **Direction Detection:** Use GTFS `direction_id` to set Trip.inbound
2. **Timing Status:** Map GTFS `timepoint` field to StopTime.timing_status
3. **Pickup/Set Down:** Map GTFS `pickup_type` and `drop_off_type` fields
4. **Calendar Exceptions:** Implement exception date logic from calendar_dates.txt
5. **Route Geometry:** Import shapes from shapes.txt for route visualization
6. **Incremental Updates:** Add logic to update existing records instead of only creating new ones
7. **Validation:** Add GTFS validation before import
8. **Rollback:** Add automatic rollback on import failure

## Troubleshooting

### Missing GTFS Files

If you see errors about missing files, ensure your GTFS path contains:
- agency.txt
- stops.txt
- trips.txt
- stop_times.txt
- calendar.txt (optional but recommended)

### Memory Issues

For very large GTFS feeds:

1. Ensure sufficient RAM (recommend 8GB+ for full National Rail feed)
2. Use PostgreSQL with adequate memory settings
3. Consider splitting import by operator if needed

### Database Locks

The importer uses transactions and bulk operations to minimize lock time. If you encounter lock timeouts:

1. Run during low-traffic periods
2. Use `--purge` to avoid accumulation of partial data
3. Ensure adequate database connection pool size

### Duplicate Services

If you see duplicate services:

1. Check that operator NOC codes are consistent
2. Verify CRS codes in stops.txt are correct
3. Use `--purge` to clean up and re-import

## Related Commands

- `import_gtfs_rail` - Alternative rail GTFS importer (different approach)
- `import_railway_stations` - Import railway station data from other sources
- `sync_bustimes_services` - Sync services from Bustimes API

## References

- [GTFS Specification](https://gtfs.org/reference/)
- [National Rail Data Portal](https://data.atlassian.io/)
- [BetterFleet Documentation](../README.md)
