# Betterfleets incident fixes and release review — 13 November 2026

## Restored data
- FHAM: 29 current services and 17,735 trips.
- BHBC: 68 current services and 59,538 trips.
- Restored 2,086 exact route links across 1,297 services. The repair only uses active routes with an unambiguous source, service code and line match. A JSON rollback manifest is in data/timetable-link-repair-20261113T204532Z.json.
- Timetable coverage increased from 174 to 204 of 385 non-rail operators observed tracking over the preceding day. The remainder need provider downloads, missing source configuration, or operator-code mapping work; coverage is not universal.
- Repaired 62 Red Funnel journey/trip links for 13 November. Corrected East and West Cowes synthetic stop coordinates using Red Funnel's terminal-page structured data.

## Causes and changes
- BODS/Ticketer downloaded paths could be prefixed with DATA_DIR twice.
- Cleanup could detach other providers' routes simply because their operators overlapped.
- Auto-discovery used the first operator in provider metadata as a search for many unrelated datasets; stable dataset IDs are now used.
- Each BODS/Stagecoach/Ticketer source runs in a transaction and failures are isolated. Incomplete XML datasets fail instead of being finalized as complete. Dataset errors give the job a failing exit status.
- TNDS now creates its download directory. NI initializes missing source records and checks API failure responses.
- Duplicate SIRI service-code writes are idempotent. Single-operator services fill missing trip operator references.
- Nightly imports discover NOCs from recently tracking vehicles, use a process lock, write durable status, and never print credential arguments.
- New tracking identities reuse and merge matching fleet codes/numbers within the operator's group. Journeys, vehicle codes, revisions, photos, features and metadata are retained through the existing merge helper. Stagecoach's duplicate lookup no longer crashes the feed.
- Red Funnel matches the nearest departure and can match a unique crossing already underway after restart. Missing matches are retried on later updates. Ambiguous crossings remain unmatched.
- Rail allocations carry across an unambiguous same-day, same-operator terminal turnaround of at most 45 minutes. Only single-unit formations are inferred; ambiguous/coupled/overnight cases are excluded. Inferences are labelled and remain queued for authoritative RTT API confirmation.
- Removed the superuser boost UI/API and queue bypass. FIFO is the default; SWR and Southern take preference only if the estimated API queue exceeds two hours.
- Removed the RTT browser scraper, its worker and async-safety override, Playwright dependency/lock entries, and Docker Chromium installation.
- Ignore reversed upstream GTFS disruption validity periods rather than aborting the whole feed.

## Monitoring
config/monitor_critical.py runs every five minutes from noel's crontab.
- Discord notification delivery was verified.
- Alerts cover web/database/Redis availability, critical worker/container failure, unhandled exceptions in core tracking workers, FHAM/BHBC timetable loss, and nightly failure/staleness.
- Each fault sends once and repeats at most hourly while recurring. Recovery notifications are sent once. Raw logs, tokens and mentions are not sent.
- Optional disruption-feed task exceptions are excluded from log alerts; the Huey worker being absent is still critical.
- Uses CRITICAL_ERROR_WEBHOOK_URL when supplied; otherwise the existing Discord NEW_VEHICLE_WEBHOOK_URL. This deployment currently uses the existing destination.
- State and file offsets persist in betterfleets-logs/critical-monitor-state.json.
- Monitoring runs on the same host, so a total host/network outage requires external monitoring.

## Validation
- All 33 focused Django importer, RTT, fleet merge, source isolation, ferry and invalid-disruption-period tests passed.
- Django system/URL checks passed.
- Frontend TypeScript lint and production build passed.
- Python compile checks, shell syntax and Git whitespace checks passed.
- Existing broad BODS tests also expose older fixture/channel/response-shape assumptions; the entire repository test suite is not certified green.
- Public https://eeveeit.uk/ and /up returned HTTP 200.
- TLS certificate expires 18 December 2026.
- PostgreSQL migrations currently present on the server are applied.
- A verified local PostgreSQL/application backup exists at /srv/backups/betterfleets-20261113T200005Z.

## Remaining release blockers and limitations
1. BODS currently returns HTTP 403 from this host, including on the public homepage; query and header authentication both failed. Cached data restored service while this upstream/access issue persists. The next successful full nightly run still needs observing.
2. The live Compose web service uses Django runserver with DEBUG=1. Replace this with the existing production Granian image command before a public production release.
3. Django deployment checks report a weak SECRET_KEY and a non-secure session cookie. Configure a strong secret and secure cookies; key rotation invalidates existing sessions.
4. Historical nightly logs include BODS/TNDS credentials. The new wrapper and BODS API error handling avoid this; rotate the exposed credentials and restrict historical log access.
5. makemigrations --check still reports pre-existing model-state drift for OutOfServiceTrackingCode.id and VehicleRevision garage foreign keys.
6. Several already-applied migrations were not tracked in Git. They are included in the release history so fresh deployments can reproduce the current migration graph.
7. Sentry is not configured on this Compose deployment. Discord monitoring now covers the requested core operational failures, but external uptime checks and off-host backups remain release needs.
8. Django's CSRF warning requires review of the installed modern_csrf middleware; HTTPS redirect is handled at the edge and should be verified there. Clickjacking protection also needs review.

## Operations
- Import: docker exec django_web sh /app/config/import_timetables.sh
- Preview safe link recovery: docker exec django_web python manage.py repair_timetable_links
- Apply safe link recovery: append --apply; a rollback manifest is written first.
- Monitor manually: python3 config/monitor_critical.py
- Test Discord delivery: python3 config/monitor_critical.py --test-notification
