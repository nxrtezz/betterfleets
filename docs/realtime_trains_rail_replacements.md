# Realtime Trains rail replacements

The superuser page at `/fleet/rail-replacement-timetable` imports scheduled
replacement buses from the Realtime Trains next-generation API. Enter the
railway CRS codes for the endpoints (for example `SOU` and `POO`), select one
or more operating dates, and optionally enter the RTT operator code (`SW` for
South Western Railway).

Set either `RTT_API_ACCESS_TOKEN` (an issued access token) or
`RTT_API_REFRESH_TOKEN` (an issued refresh token) in the server environment.
The UUID shown as a token ID in the API portal is not usable for API calls and
cannot be exchanged; it must not be used as `RTT_API_TOKEN`. The token is a
bearer credential and must not be placed in browser JavaScript, templates, or a
distributable application. `RTT_API_BASE_URL` defaults to `https://data.rtt.io`;
use `RTT_API_VERSION` only when pinning a version supported by the token.

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
