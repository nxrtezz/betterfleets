# Network Rail CIF Schedule Import Documentation

This document describes the Network Rail CIF (Common Interface Format) schedule data import system for BetterFleet.

## Overview

The `import_nwr_services` management command imports UK National Rail CIF schedule data from the `/NWR/` folder and automatically populates service definitions, timetable entries, and calling patterns with intelligent deduplication.

## Migration from GTFS

This system replaces the GTFS-based ingestion entirely. CIF/NWR data is now the source of truth for all rail timetable information.

## Data Source

### CIF Files Location

All raw timetable data is stored in:

```
/NWR/
```

### File Structure

The folder contains:

- **CIF_ALL_FULL_DAILY_toc-full.json.gz** - Primary full schedule dataset
- **CIF_ALL_UPDATE_DAILY_*.json.gz** - Incremental daily updates

### CIF JSON Format

The CIF files are in JSON Lines format (one JSON object per line):

```json
{"JsonTimetableV1":{"classification":"public","timestamp":1782088287,...}}
{"TiplocV1":{"transaction_type":"Create","tiploc_code":"AACHEN","crs_code":null,...}}
{"ScheduleV1":{"train_uid":"G12345","atoc_code":"SW","schedule_segment":{...}}}
```

## Command Usage

```bash
python manage.py import_nwr_services --path /NWR
```

### Options

- `--path` (default: `/NWR`) - Path to NWR folder containing CIF JSON files
- `--full` - Import full schedule file only (CIF_ALL_FULL_DAILY_*.json.gz)
- `--apply-updates` - Apply incremental update files (CIF_ALL_UPDATE_DAILY_*.json.gz)
- `--purge` - Remove previously imported NWR services and rebuild from scratch

### Examples

**Import latest full schedule:**
```bash
python manage.py import_nwr_services --path /NWR
```

**Import with purge (clean rebuild):**
```bash
python manage.py import_nwr_services --path /NWR --purge
```

**Apply incremental updates:**
```bash
python manage.py import_nwr_services --path /NWR --apply-updates
```

## Data Model

### New Models

#### TimetableEntry

A specific scheduled journey (train working) from CIF schedule data.

**Fields:**
- `service` - ForeignKey to Service
- `train_uid` - Unique train identifier (e.g., "G12345")
- `headcode` - Train headcode (e.g., "2A45")
- `departure_time` - Departure time from origin
- `arrival_time` - Arrival time at destination
- `schedule_start_date` - Schedule validity start date
- `schedule_end_date` - Schedule validity end date
- `monday` through `sunday` - Operating day flags
- `atoc_code` - ATOC/TOC code (e.g., "SW" for South Western Railway)
- `transaction_type` - CIF transaction type (Create/Update/Delete)

**Unique Constraint:**
- `(train_uid, schedule_start_date)`

#### CallingPoint

A stop on a timetable entry (calling pattern).

**Fields:**
- `timetable_entry` - ForeignKey to TimetableEntry
- `station` - ForeignKey to StopPoint
- `arrival_time` - Arrival time at this stop
- `departure_time` - Departure time from this stop
- `tiploc_code` - Original TIPLOC code from CIF
- `sequence` - Order in journey (0, 1, 2, ...)
- `pick_up` - Whether passengers can board
- `set_down` - Whether passengers can alight
- `timing_status` - CIF timing status

**Unique Constraint:**
- `(timetable_entry, station, sequence)`

## Import Process

### Phase 1: Load Data

The importer scans the NWR folder and selects appropriate files based on options:

- Default: Latest full file only
- `--full`: All full files
- `--apply-updates`: Full + update files

### Phase 2: Build Station Map

TIPLOC codes are resolved to CRS codes and Station records:

1. **Read TiplocV1 entries** from CIF files
2. **Extract CRS codes** where available
3. **Match to existing StopPoint records** by CRS code
4. **Fallback to description matching** if CRS not found
5. **Build TIPLOC → Station lookup cache**

**Resolution Rate:**
The importer reports the percentage of TIPLOCs successfully resolved to stations.

### Phase 3: Generate Services

Services are generated with deduplication based on:

```
(operator_id, origin_crs, destination_crs)
```

**Service Naming:**

**Line Name Format:**
```
{origin_crs} - {destination_crs}
```

Examples:
- `SOU - BTN` (Southampton Central to Brighton)
- `VIC - BTN` (London Victoria to Brighton)
- `KGX - EDB` (London King's Cross to Edinburgh)

**Description Format:**
```
{origin_name} - {destination_name}
```

Examples:
- `Southampton Central - Brighton`
- `London Victoria - Brighton`
- `London King's Cross - Edinburgh`

**Operator Mapping:**
- ATOC codes from CIF are matched to existing Operator records by NOC
- New Operator records are created if no match found
- All operators are set to `vehicle_mode="rail"`

### Phase 4: Generate Timetables

Each CIF schedule becomes one TimetableEntry:

**Fields Extracted:**
- `train_uid` - From CIF `train_uid`
- `headcode` - From CIF `train_identity` or `headcode`
- `departure_time` - From first location's `departure`
- `arrival_time` - From last location's `arrival`
- `schedule_start_date` - From CIF `schedule_start_date`
- `schedule_end_date` - From CIF `schedule_end_date`
- `operating_days` - From CIF `days_run` bitmask
- `atoc_code` - From CIF `atoc_code`

**Deduplication:**
- Unique constraint on `(train_uid, schedule_start_date)`
- Prevents duplicate entries for same schedule

### Phase 5: Generate Calling Points

For each schedule, ordered calling points are created:

**Fields Extracted:**
- `station` - Resolved from TIPLOC
- `arrival_time` - From location `arrival`
- `departure_time` - From location `departure`
- `sequence` - Order in schedule (0, 1, 2, ...)
- `tiploc_code` - Original TIPLOC preserved
- `timing_status` - From CIF `timing_status`

**Unresolved Stations:**
- Stations that cannot be resolved are skipped
- TIPLOC code is preserved for future mapping

## Performance Optimizations

The importer is designed to handle large CIF feeds efficiently:

### Streaming

- **JSON Lines parsing:** Line-by-line reading, no full in-memory load
- **Generator pipelines:** Process data as it's read
- **Gzip streaming:** Direct decompression during parsing

### Batch Operations

- **Services:** Individual creation with deduplication cache
- **TimetableEntries:** Bulk create with batch_size=1000
- **CallingPoints:** PostgreSQL COPY command for maximum performance

### Caching

- **Service cache:** Dictionary for O(1) deduplication lookup
- **TIPLOC cache:** Single-pass resolution, reused across all schedules
- **Station cache:** Resolved stations stored for quick lookup

### Memory Management

- **No full dataset loading:** Process line-by-line
- **Selective field loading:** Only extract needed fields
- **Transaction batching:** Commit in batches to avoid long transactions

## Progress Logging

The command provides detailed progress output:

```
Loading NWR schedule files...
Reading TIPLOCs from CIF_ALL_FULL_DAILY_toc-full.json.gz...
Resolving stations (TIPLOC → CRS)...
Resolved stations: 98.2% (2500/2545)
Parsing CIF schedule feeds...
Parsing schedules from CIF_ALL_FULL_DAILY_toc-full.json.gz...
Schedules found: 1,240,000
Generating services...
Southern: 18 services
SWR: 34 services
LNER: 22 services
Services created: 412
Generating timetables...
Timetable entries created: 1,240,000
Generating calling points...
Calling points created: 19,400,000
Import complete.
```

## Purge Functionality

The `--purge` option removes all previously imported NWR data:

1. Deletes CallingPoint records for NWR timetable entries
2. Deletes TimetableEntry records for NWR services
3. Deletes Service records for NWR source
4. Deletes the DataSource record

This is performed within a transaction to ensure atomicity.

## Data Relationships

The resulting data structure:

```
Operator (busstops.Operator)
 └─ Service (busstops.Service)
     ├─ TimetableEntry (bustimes.TimetableEntry)
     │   └─ CallingPoint (bustimes.CallingPoint)
     └─ StopPoint (busstops.StopPoint) [via Service.stops]
```

### Example

```
Operator: Southern (noc: SOU)
 └─ Service: SOU - BTN
     ├─ TimetableEntry: G12345 (06:14 SOU → BTN)
     │   ├─ CallingPoint: Southampton Central (06:14)
     │   ├─ CallingPoint: Fareham (06:38)
     │   └─ CallingPoint: Brighton (08:14)
     ├─ TimetableEntry: G12346 (07:14 SOU → BTN)
     └─ TimetableEntry: G12347 (08:14 SOU → BTN)
```

## TIPLOC Resolution

### Resolution Strategy

1. **CRS Code Match:** Direct lookup by `crs_code` in StopPoint
2. **Description Match:** Fuzzy match by station name
3. **Unresolved:** Mark as unresolved, preserve TIPLOC for future mapping

### Improving Resolution

To improve TIPLOC resolution rates:

1. **Import station data** from official sources (Network Rail, NAPTAN)
2. **Add manual mappings** for common TIPLOCs
3. **Use CORPUS data** if available for additional mappings
4. **Regular maintenance** as TIPLOC codes change over time

## CIF Format Details

### ScheduleV1 Structure

```json
{
  "ScheduleV1": {
    "train_uid": "G12345",
    "train_identity": "2A45",
    "atoc_code": "SW",
    "schedule_start_date": "2024-01-01",
    "schedule_end_date": "2024-12-31",
    "days_run": "MTWRFSS",
    "schedule_segment": {
      "schedule_location": [
        {
          "tiploc_code": "SOUTHMPT",
          "departure": "0614",
          "arrival": "0614",
          "timing_status": "PTP"
        },
        ...
      ]
    }
  }
}
```

### TiplocV1 Structure

```json
{
  "TiplocV1": {
    "transaction_type": "Create",
    "tiploc_code": "SOUTHMPT",
    "crs_code": "SOU",
    "description": "SOUTHAMPTON CENTRAL",
    "tps_description": "SOUTHAMPTON CENTRAL"
  }
}
```

### Days Run Format

CIF uses a bitmask string for operating days:
- `M` - Monday
- `T` - Tuesday
- `W` - Wednesday
- `R` - Thursday
- `F` - Friday
- `S` - Saturday
- `O` - Sunday

Example: `MTWRFSS` = Daily service
Example: `MTWRF` = Weekdays only

## Re-running Imports

### Full Re-import

To completely refresh the data:

```bash
python manage.py import_nwr_services --path /NWR --purge
```

### Incremental Update

To apply daily updates:

```bash
python manage.py import_nwr_services --path /NWR --apply-updates
```

**Note:** The deduplication logic is based on `(train_uid, schedule_start_date)`. If these values change in the CIF feed, new entries will be created rather than updating existing ones.

## Troubleshooting

### Low TIPLOC Resolution Rate

If resolution rate is below 90%:

1. Check that StopPoint records have CRS codes populated
2. Import additional station data from official sources
3. Add manual TIPLOC → CRS mappings
4. Verify TIPLOC codes haven't changed in the CIF feed

### Memory Issues

For very large CIF feeds:

1. Ensure sufficient RAM (recommend 8GB+ for full national timetable)
2. Use PostgreSQL with adequate memory settings
3. Process full files separately from updates if needed

### Database Locks

The importer uses transactions and bulk operations to minimize lock time. If you encounter lock timeouts:

1. Run during low-traffic periods
2. Use `--purge` to avoid accumulation of partial data
3. Ensure adequate database connection pool size

### Duplicate Services

If you see duplicate services:

1. Check that operator NOC codes are consistent
2. Verify CRS codes in TiplocV1 are correct
3. Use `--purge` to clean up and re-import

## Migration from GTFS

To migrate from GTFS to CIF:

1. **Backup existing data:** Export any customizations
2. **Purge GTFS data:** Use `--purge` on GTFS importer
3. **Import CIF data:** Run `import_nwr_services --purge`
4. **Verify data:** Check service counts and timetable entries
5. **Update integrations:** Update any code using GTFS-specific fields

## Future Enhancements

Potential improvements:

1. **Incremental Updates:** Implement proper update/delete handling
2. **Calendar Exceptions:** Implement exception date logic from CIF
3. **Route Geometry:** Import shapes from CIF for route visualization
4. **Platform Information:** Add platform data from CIF
5. **Real-time Integration:** Link to Darwin real-time feeds
6. **Performance:** Further optimize for sub-10 minute full import
7. **Validation:** Add CIF validation before import
8. **Rollback:** Add automatic rollback on import failure

## Related Commands

- `import_gtfs_services` - Legacy GTFS importer (deprecated)
- `import_railway_stations` - Import railway station data from other sources
- `sync_bustimes_services` - Sync services from Bustimes API

## References

- [Network Rail Open Data](https://data.networkrail.co.uk/)
- [CIF Specification](https://www.networkrail.co.uk/industry-commercial/information-for-industry/data-feeds/cif/)
- [BetterFleet Documentation](../README.md)
