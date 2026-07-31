# Model Catalogue

This catalogue covers live Django models outside the reference directories. Each model is retained because it is part of runtime data, import state, public pages, admin workflows, approval history, or compatibility migrations.

## Accounts

| Model | Purpose | Status |
| --- | --- | --- |
| `Invitation` | Invitation token/email flow for controlled account creation. | Active. Used by registration admin/forms/tests. |
| `RegistrationSettings` | Singleton-style switch for whether public registration is open. | Active. Used by registration forms/views. |
| `OperatorUser` | Links users to operators they can represent or administer. | Active. Used by account/admin permissions. |

## Bus Stops, Operators, And Services

| Model | Purpose | Status |
| --- | --- | --- |
| `Region` | Top-level geography for services, operators, and admin areas. | Active. |
| `AdminArea` | NaPTAN administrative area. | Active. |
| `District` | Subdivision of an admin area. | Active. |
| `Locality` | Searchable town/locality hierarchy for stops. | Active. |
| `StopArea` | NaPTAN grouped stop area such as a bus station. | Active. |
| `StopGroup` | Manually curated stop grouping used for richer public pages. | Active. |
| `StopGroupStop` | Ordered through table between stop groups and stops. | Active. |
| `DataSource` | Source metadata for imported stop/operator/service data. | Active. |
| `BustimesSyncState` | Last imported Bustimes API state, used for field-level protection. | Active. |
| `DataChangeLog` | Audit and approval queue for command/import driven changes. | Active. |
| `StopPoint` | Individual public transport stop. | Active. |
| `Organisation` | Parent brand/company profile for operator groups/operators. | Active. |
| `Depot` | Legacy operator location model. Garage is now primary. | Compatibility only; retained for migration/backfill and old data safety. |
| `OperatorGroup` | Operator grouping for organisations, fleet views, and themes. | Active. |
| `OperatorGroupDepot` | Legacy group-level location model. Garage is now primary. | Compatibility only; hidden from primary admin. |
| `Operator` | Operating company/operator identity and public profile. | Active. |
| `StopCode` | Alternate source-specific stop codes. | Active. |
| `OperatorCode` | Alternate operator identifiers from import sources. | Active. |
| `StopUsage` | Service/stop usage index for route and departure views. | Active. |
| `ServiceColour` | Shared colour/brand metadata for services and maps. | Active. |
| `Service` | Public service/route grouping used by timetables, pages, maps, and APIs. | Active. |
| `RouteNotice` | Planned notices/diversions attached to services. | Active. |
| `ServiceCode` | Alternate source-specific service identifiers. | Active. |
| `ServiceLink` | Relationship between services. | Active. |
| `HomepageNotice` | Admin-controlled notice on public pages. | Active. |
| `PaymentMethod` | Fare/payment capability shown for operators/services. | Active. |
| `ServicePaymentMethod` | Through table between services and payment methods. | Active. |
| `Contact` | Public/contact workflow record. | Active. |
| `SIRISource` | Real-time data source configuration for SIRI feeds. | Active. |

## Timetables

| Model | Purpose | Status |
| --- | --- | --- |
| `TimetableDataSource` | Source-level timetable import configuration and search metadata. | Active. |
| `Version` | Imported timetable version metadata. | Active. |
| `Route` | Imported timetable route pattern linked to services. | Active. |
| `RouteLink` | Geometry link between route stops. | Active. |
| `BankHoliday` | Bank holiday calendar group. | Active. |
| `BankHolidayDate` | Date entries for bank holidays. | Active. |
| `CalendarBankHoliday` | Through model between calendars and bank holidays. | Active. |
| `Calendar` | GTFS/TransXChange/ATCO service calendar. | Active. |
| `CalendarDate` | Calendar exceptions. | Active. |
| `Note` | Timetable note text/code. | Active. |
| `Trip` | Scheduled trip/journey. | Active. |
| `StopTime` | Stop-level times for trips. | Active. |
| `Garage` | Primary operational location/depot model for vehicles and trips. | Active. Replaces Depot as the primary location object. |
| `VehicleType` | Timetable-imported vehicle type. | Active. Separate from fleet `vehicles.VehicleType`. |

## Disruptions

| Model | Purpose | Status |
| --- | --- | --- |
| `Situation` | Disruption/SIRI situation record. | Active. |
| `Link` | URL/link attached to a situation. | Active. |
| `ValidityPeriod` | Active period for a situation. | Active. |
| `Consequence` | Affected services/stops/operators for a situation. | Active. |
| `AffectedJourney` | Journey-level effect of a situation. | Active. |
| `Call` | Stop call impact attached to affected journeys. | Active. |

## Fares

| Model | Purpose | Status |
| --- | --- | --- |
| `DataSet` | Imported fare dataset metadata. | Active. |
| `TimeInterval` | Fare validity interval. | Active. |
| `SalesOfferPackage` | NeTEx sales offer package. | Active. |
| `PreassignedFareProduct` | NeTEx fare product. | Active. |
| `UserProfile` | NeTEx/user profile fare applicability. | Active. |
| `Tariff` | Imported tariff. | Active. |
| `Price` | Fare price amount/currency. | Active. |
| `FareTable` | Matrix/table of fares. | Active. |
| `FareZone` | Fare zone metadata. | Active. |
| `DistanceMatrixElement` | Zone-to-zone or stop-to-stop fare relationship. | Active. |
| `Column` | Fare table column. | Active. |
| `Row` | Fare table row. | Active. |
| `Cell` | Fare table cell value. | Active. |
| `Fare` | Legacy/simple fare record. | Active. |
| `FareRule` | Rule linking fares to routes/zones. | Active. |

## Photos

| Model | Purpose | Status |
| --- | --- | --- |
| `Photo` | Photo metadata and uploaded image relation. | Active. |

## Vehicles

| Model | Purpose | Status |
| --- | --- | --- |
| `VehicleType` | Fleet vehicle type/classification. | Active. Separate from timetable `bustimes.VehicleType`. |
| `Livery` | Vehicle livery/colour presentation metadata. | Active. |
| `VehicleFeature` | Feature flags/amenities for vehicles. | Active. |
| `Vehicle` | Fleet vehicle record and public vehicle page source. | Active. |
| `VehicleCode` | Alternate vehicle identifiers from imported sources. | Active. |
| `VehicleRevisionFeature` | Through model for revision feature changes. | Active. |
| `VehicleRevision` | Manual approval/changelog workflow for vehicle edits. | Active. |
| `VehicleJourney` | Observed/live vehicle journey record. | Active. |
| `SiriSubscription` | Real-time SIRI subscription configuration. | Active. |

## Review Notes

- No model was safe to remove from source in this pass. All models are either directly registered in admin, referenced by imports/views/tests/templates, or needed for migration/backward compatibility.
- `Depot` and `OperatorGroupDepot` should remain until production data has been migrated and external admin/runbook usage has been retired. New code should prefer `bustimes.Garage`.
- The two `VehicleType` models are similarly named but represent different domains. They should not be merged without a separate migration/design pass.
