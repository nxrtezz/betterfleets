# Management Commands

This repo keeps externally callable commands unless they are verified unused. A command is safe to remove only when repo references, admin/docs/scripts, tests, and deployment runbooks all show it is unused.

## Data safety policy

- Commands that mutate data should expose `--dry-run` where practical.
- Commands that import or sync data must record applied changes in `DataChangeLog`.
- Commands must queue pending changelog rows instead of overwriting manual user data.
- Commands with possible external cron/manual usage should be deprecated before deletion.

## Current command groups

### Stops and operators

- `import_noc`
- `naptan_new`
- `nptg_new`
- `update_search_indexes`
- `update_slugs`
- `fix_service_operators`
- `jersey_routes`
- `jersey_stops`
- `import_tfl`
- `osm_iom_stops`

### Bustimes API sync

- `sync_bustimes_stops`
- `sync_bustimes_services`
- `sync_bustimes_vehicles`
- `sync_bustimes_liveries`
- `sync_bustimes_journeys`

These use the shared Bustimes sync layer. Applied changes are logged, and protected manual-field conflicts are queued for approval.

### Timetables and fares

- `import_atco_cif`
- `import_bod_timetables`
- `import_gtfs`
- `import_gtfs_ember`
- `import_gtfs_flixbus`
- `import_ni`
- `import_passenger`
- `import_timetable_data`
- `import_tnds`
- `import_transxchange`
- `purge_services_and_reimport`
- `suggest_bod`
- `bank_holidays`
- `import_netex_fares`
- `mytrip_ticketing`

These commands should be treated as production data-entry paths. Before any future removal, check external schedulers and operator runbooks.

## Smoke testing

Use `--help` for every retained command after dependency installation:

```bash
uv run ./manage.py help sync_bustimes_vehicles
uv run ./manage.py sync_bustimes_vehicles --help
```

For mutating imports, prefer command-specific fixture inputs and `--dry-run` where available.
