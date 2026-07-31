# Data Change Control

Automatic imports and sync jobs must leave a durable audit trail. Manual user data must not be overwritten by a command unless a pending change has been reviewed and approved.

## Changelog model

`busstops.DataChangeLog` records command/import changes with:

- source command or importer name
- target model and primary key
- operation type
- field-level before/after changes
- source payload
- status: `pending`, `applied`, or `rejected`
- approval metadata

Applied import-owned changes are written immediately with an `applied` changelog row. Protected manual-field conflicts are written as `pending` rows and are not applied until approved.

## Approval flow

1. Open Django admin.
2. Go to `Data change logs`.
3. Filter to `Pending approval`.
4. Review the field diff and source payload.
5. Use `Approve and apply selected pending data changes` or `Reject selected pending data changes`.

Approval applies only the field values stored in the changelog row. Rejection leaves the existing manual value untouched.

## Command rules

- Mutating commands should support `--dry-run` where practical.
- Dry-runs must not create sync state or changelog rows.
- Commands that change records must either log applied changes or queue pending manual-field changes.
- Bulk imports should be wrapped in transactions around each coherent unit of work.
- New automatic data sources must define which fields are import-owned before they write live data.
