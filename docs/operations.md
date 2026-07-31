# Operations

Production startup is managed with tmux scripts in `scripts/`.

## Required tools

- `tmux`
- `cloudflared`
- Python dependencies installed in `.venv`
- configured `DATABASE_URL`, `SECRET_KEY`, `ALLOWED_HOSTS`, and any importer credentials

## Cloudflare tunnel

The scripts do not hard-code a tunnel name or credentials. Set one of:

```bash
export CLOUDFLARED_COMMAND='cloudflared tunnel --config /etc/cloudflared/config.yml run'
export CLOUDFLARED_CONFIG=/etc/cloudflared/config.yml
export CLOUDFLARED_TUNNEL=betterfleet
```

`CLOUDFLARED_COMMAND` wins when set. Otherwise the script uses `CLOUDFLARED_CONFIG`, then `CLOUDFLARED_TUNNEL`.

## Start

```bash
scripts/start-production.sh
```

Defaults:

- tmux session: `betterfleet`
- app window: `.venv/bin/gunicorn buses.wsgi:application -c gunicorn.conf.py`
- Huey window: `.venv/bin/python manage.py run_huey`
- tunnel window: resolved Cloudflare command

Useful overrides:

```bash
export BETTERFLEET_TMUX_SESSION=betterfleet
export BETTERFLEET_ROOT=/srv/betterfleet
export BETTERFLEET_APP_COMMAND='.venv/bin/gunicorn buses.wsgi:application -c gunicorn.conf.py'
export BETTERFLEET_ENABLE_HUEY=0
export BETTERFLEET_HUEY_COMMAND='.venv/bin/python manage.py run_huey'
```

## Stop and restart

```bash
scripts/stop-production.sh
scripts/restart-production.sh
```

## Release checks

Run these before promoting a build:

```bash
uv run ./manage.py migrate --check
uv run ./manage.py check --deploy
uv run ./manage.py collectstatic --noinput
npm run build
npm test -- --runInBand
```

On Windows shells, run Jest with:

```powershell
$env:TZ='UTC'; npx jest --runInBand
```
