# Release Audit

Reference directories excluded from this audit:

- `bustimes_REFERENCE/`
- `TransportStatistics_REFERENCE/`

## Findings

- Existing Bustimes sync code already had field-level protection via `BustimesSyncState`, but skipped manual-field conflicts were not visible in an approval queue.
- `Garage` is already the correct long-term operational location model and now has location/address migrations plus admin support.
- Legacy Depot admin pages were duplicative with Garage admin. They are hidden from admin, while legacy model data is backfilled into Garages by migration.
- The working tree had existing changes before this audit. No unrelated changes were reverted.
- Frontend Jest tests pass when `TZ` is set in a Windows-compatible way.
- Django checks require GDAL and a configured database environment.

## Release blockers to clear in deployment-like environment

- Install GDAL/PostGIS dependencies and run Django checks.
- Set `DATABASE_URL` and run migrations.
- Run `manage.py check --deploy`.
- Smoke-test retained management commands with `--help` and command-specific dry-runs.
- Confirm no external scheduler still expects legacy Depot admin workflows.

## Retained code

No management command was deleted in this pass. Commands can be called externally by cron, tmux sessions, manual runbooks, or hosting tasks, so the policy is verified removal or deprecation first.
