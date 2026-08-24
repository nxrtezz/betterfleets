# Development Environment Setup

This document describes the isolated development environment for BetterFleets V2, accessible at `dev.eeveeit.uk`.

## Overview

The dev environment is completely isolated from production:
- **Separate database**: `betterfleets_dev` with user `dev_user`
- **Separate containers**: `bfdev-django`, `bfdev-postgres`, `bfdev-redis`
- **Separate volumes**: `postgres_data_dev`, `media_dev`
- **Separate ports**: Web exposed on `18000:8000` (internal 8000, external 18000)
- **Separate environment file**: `.env.dev`
- **Separate Dockerfile**: `Dockerfile.dev` (uses standard Python base instead of custom base image)

## Files Created

1. `docker-compose.dev.yml` - Dev Docker Compose configuration
2. `.env.dev` - Dev environment variables
3. `Dockerfile.dev` - Dev Dockerfile (uses standard Python base image)
4. `nginx-dev.conf` - Nginx server block for dev.eeveeit.uk (if using nginx)

## Git Workflow for V2 Development

BetterFleets V2 development uses a dedicated `dev` branch to ensure production safety:

1. **Switch to development branch:**
   ```bash
   git checkout dev
   ```

2. **Make V2 changes on the dev branch only**

3. **Switch back to production when needed:**
   ```bash
   git checkout main
   ```

4. **Merge V2 changes to production when ready:**
   ```bash
   git checkout main
   git merge dev
   ```

**Important:** Never make V2 changes directly on the `main` branch. The `dev` branch isolates all V2 development work from production.

## Run Commands

### Build the dev stack

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev build
```

### Start the dev environment

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev up -d
```

### Stop the dev environment

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev down
```

### View dev logs

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev logs -f
```

### Run migrations on dev database

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev exec web_dev python manage.py migrate
```

### Create superuser for dev

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev exec web_dev python manage.py createsuperuser
```

### Access Django shell in dev

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev exec web_dev python manage.py shell
```

### Collect static files for dev

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev exec web_dev python manage.py collectstatic
```

## Nginx Configuration

1. Copy `nginx-dev.conf` to your nginx configuration directory:
   ```bash
   sudo cp nginx-dev.conf /etc/nginx/sites-available/dev.eeveeit.uk
   ```

2. Create symlink to enable the site:
   ```bash
   sudo ln -s /etc/nginx/sites-available/dev.eeveeit.uk /etc/nginx/sites-enabled/
   ```

3. Test nginx configuration:
   ```bash
   sudo nginx -t
   ```

4. Reload nginx:
   ```bash
   sudo systemctl reload nginx
   ```

5. Obtain SSL certificate (optional, recommended):
   ```bash
   sudo certbot --nginx -d dev.eeveeit.uk
   ```

## Isolation Details

### Database
- **Production**: `postgres` database, user `postgres`, password `postgres`
- **Dev**: `betterfleets_dev` database, user `dev_user`, password `dev_password`

### Volumes
- **Production**: `postgres_data`, media directory
- **Dev**: `postgres_data_dev`, `media_dev` volume

### Container Names
- **Production**: `django_web`, `postgres`, `redis`
- **Dev**: `bfdev-django`, `bfdev-postgres`, `bfdev-redis`

### Ports
- **Production**: Web on `8000:8000`
- **Dev**: Web on `18000:8000`

### Environment Variables
- **Production**: Uses `.env`
- **Dev**: Uses `.env.dev` with `DEBUG=1` and dev-specific settings

## Accessing the Dev Environment

- **Direct access**: http://localhost:18000
- **Via Nginx**: http://dev.eeveeit.uk (after nginx configuration)
- **Django admin**: http://dev.eeveeit.uk/admin (after creating superuser)

## Switching Between Production and Development

### To switch to development environment:
1. Ensure Docker Desktop is running
2. Stop production if running: `docker compose down`
3. Start development: `docker compose -f docker-compose.dev.yml --env-file .env.dev up -d`
4. Access at http://localhost:18000

### To switch back to production:
1. Stop development: `docker compose -f docker-compose.dev.yml --env-file .env.dev down`
2. Start production: `docker compose up -d`
3. Access at http://localhost:8000

### Running both environments simultaneously:
Both environments can run at the same time since they use different ports and containers:
- Production: `docker compose up -d` (port 8000)
- Development: `docker compose -f docker-compose.dev.yml --env-file .env.dev up -d` (port 18000)

## Cleanup

To completely remove the dev environment (including volumes):

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev down -v
```

To remove dev environment and images:

```bash
docker compose -f docker-compose.dev.yml --env-file .env.dev down -v --rmi all
```

## Notes

- The dev environment uses Django's development server (`runserver`) for hot reload
- DEBUG is enabled in dev mode
- The dev environment does not affect production in any way
- Both environments can run simultaneously

## V2 Development Safety Checklist

Before starting V2 feature development, verify:

- [ ] You are on the `dev` branch: `git branch` should show `* dev`
- [ ] Docker Desktop is running
- [ ] Development environment can start: `docker compose -f docker-compose.dev.yml --env-file .env.dev up -d`
- [ ] Development database is accessible: `docker compose -f docker-compose.dev.yml --env-file .env.dev exec web_dev python manage.py migrate`
- [ ] Development environment is accessible at http://localhost:18000
- [ ] Production environment remains unaffected: `docker ps` should not show production containers if they were stopped

## V2 Development Process

1. Ensure you're on the `dev` branch
2. Start the development environment
3. Make your changes
4. Test in the development environment
5. Commit changes to the `dev` branch
6. Push to GitHub: `git push origin dev`
7. When V2 is complete, merge to `main` for production deployment
