# BetterFleets

BetterFleets is a bus fleet tracking and logging application, forked from [bustimes.org](https://bustimes.org/). This project adds Discord bot integration, driver logging functionality, and enhanced user features while maintaining the core vehicle tracking capabilities.

**Credit:** BetterFleets is based on the excellent [bustimes.org](https://bustimes.org) project by James Goodwin. The original project provides the foundation for bus tracking, timetables, and vehicle management.

## What's this?

Source code for the BetterFleets application, a fork of [bustimes.org](https://bustimes.org/). BetterFleets adds Discord bot integration, driver logging, and enhanced user features to the original bus tracking platform.

It's a magnificent monolithic Django app that's evolved over time (since 2015). The structure doesn't make complete sense:

app      | concern
---------|------------
accounts | user accounts
api      | the Django Rest Framework–powered API
buses    | contains the site settings.py
busstops | bus stops - but also operating companies, places, and routes 🤯 and the site's static file assets
bustimes | getting timetable data out of various formats (GTFS, TransXChange, ATCO-CIF) and into a database and doing stuff therewith
config   | Kamal and Supervisor configuration
departures | listing the "next departures" at a bus stop – from a timetable and/or predicted by an API
disruptions | information about like roadworks, diversions and stuff
fares    | fares
fleet    | fleet-completion, ride, photo, and driving logs
fixtures | some YAML files containing overrides/corrections to the operator (NOC) and bus stop (NaPTAN) datasets. Also recorded HTTP responses used in tests
frontend | TypeScript and Sass bits
service_logging | per-user route completion logs
transxchange | code for parsing TransXChange XML files. Could be published as a separate package
vehicles | tracking buses' locations and showing them on a map, and pointless details about vehicles' colours and features
vosa     | the Great Britain Traffic Commissioners' bus service registration data. VOSA is the name of a defunct UK government agency.

I try to document things for "future me", but invariably this documentation will be incomplete and out of date in parts.

## Project docs

- [Operations and tmux startup](docs/operations.md)
- [Data change control and changelog approvals](docs/data-change-control.md)
- [Model catalogue](docs/models.md)
- [Management command inventory and removal policy](docs/management-commands.md)
- [Release audit notes](docs/release-audit.md)
- [API Usage](docs/API_USAGE.md)
- [Development Environment Setup](docs/DEV_ENVIRONMENT_SETUP.md)
- [Train Tracking Setup](docs/setup_train_tracking.md)
- [Discord Release Message](docs/discord_release_message.md)
- [Photo Log Plan](docs/Photo-Log-Plan.md)

## License note

Some of the **test data** in this repository is public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

This repository also contains some **font files** which are copyrighted and not covered by the main [licence](LICENSE).

## Installing

### Using Docker

I don't know. These days, I only use Docker for running the production site (see below).

### Using local install

These need to be available:

- Python 3.14
- `uv` to install necessary Python packages (Django, etc)
- PostgreSQL with PostGIS
    - On my Macintosh computer I use [Postgres.app](https://postgresapp.com/)
- `npm` to install some front end JavaScript things
- Redis 6.2+
- [GDAL](https://gdal.org/)

Useful commands that you might need to run from time to time:

```bash
npm install  # install JavaScript dependencies
npm run build  # build the front-end CSS and JavaScript
npm run watch  # build the front-end CSS and JavaScript in development mode, and "watch" and rebuild when the source changes
uv sync --group dev --group test  # install Python dependencies including special ones for development and testing
uv run ./manage.py collectstatic
uv run ./manage.py migrate  # create database tables
uv run ./manage.py runserver 0.0.0.0:8000  # run the Django development server (not suitable for production, use gunicorn for that!)
```

Some environment variables need to be set.
Many of them control settings in [buses/settings.py](buses/settings.py).

```bash
DEBUG=0
SECRET_KEY=something
DATABASE_URL=postgis://user:password@host/database-name
```

[.github/workflows/test.yml](.github/workflows/test.yml) sort of documents the process of installing dependencies and running tests.

## Importing data

### Static data (stops, timetables, etc)

[import.sh](import.sh) will download *some* data from various [sources](https://bustimes.org/data) and run the necessary Django [management commands](busstops/management/commands) to import it,
in a sensible order (place names, then stops, then timetables).
When run repeatedly, it will only download and import the stuff that's changed.
It needs a username and password for the Traveline National Dataset step.

But then there are further management commands for getting further data from further places like the Bus Open Data Service.

### Live data

Some "live" data – departure times at stops, and vehicle locations – is/are fetched as and when a user accesses a page.

For the rest, there are some Django management commands that need to be run indefinitely in the background.
These update the big map of bus locations, etc.
I use supervisord (see [config/supervisor.conf](config/supervisor.conf)).

## BetterFleets Features

In addition to the core features from bustimes.org, BetterFleets includes:

- **Discord Bot Integration**: Slash commands for logging vehicles, checking completion stats, and linking Discord accounts
- **Driver Logging**: Separate tracking for vehicles driven (vs. ridden as a passenger)
- **Driver Status Requests**: Users can request driver status with admin approval workflow
- **Enhanced Notifications**: Color-coded Discord embeds with approve/deny buttons for revisions
- **User Account Linking**: Connect Discord accounts to BetterFleets user accounts via 6-digit codes
- **Route Completion**: Users can log routes they have ridden from a service page. Route lists show a tick for ridden routes, a cross for unlogged public routes, and a dash for non-public routes. Non-public routes can still be logged and are included in a user's ridden total.
- **Public Profile Stats**: Profiles whose owners have enabled public fleet logging show vehicle, photo, and route-completion totals. The livery tab groups the user's logged vehicles by operator and livery.

## Deploying

Uses [Kamal](https://kamal-deploy.org/  ) (see [config/deploy.yml](config/deploy.yml))
