# Realtime Trains rail replacements

The superuser page at `/fleet/rail-replacement-timetable` imports scheduled
replacement buses from the Realtime Trains next-generation API. Enter the
railway CRS codes for the endpoints (for example `SOU` and `POO`), select one
or more operating dates, and optionally enter the RTT operator code (`SW` for
South Western Railway).

Set `RTT_API_TOKEN` in the server environment. The token is a bearer token and
must not be placed in browser JavaScript, templates, or a distributable
application. `RTT_API_BASE_URL` defaults to `https://data.rtt.io`; use
`RTT_API_VERSION` only when pinning a version supported by the token.

The importer queries `/gb-nr/location` to discover candidates and
`/gb-nr/service` for ordered calling points. It keeps only replacement-bus
services, creates separate timetable groups for different complete calling
patterns, and imports both directions. Generated records are immediately
available as rail-replacement `Trip` records. The Overland generator can
select an exact generated trip; its location feed then creates a
`VehicleJourney` linked to that scheduled trip and service.

The free RTT tier is rate-limited and may restrict detailed mode or history.
The importer reports API failures instead of creating partial timetable data.
If RTT does not provide a replacement-bus service in its Network Rail feed, it
cannot be generated automatically from this source.
