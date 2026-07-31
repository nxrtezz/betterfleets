# Development Environment Setup

This document describes the isolated development environment for betterfleets, accessible at `dev.eeveeit.uk`.

## Overview

The dev environment is completely isolated from production:
- **Separate database**: `betterfleets_dev` with user `dev_user`
- **Separate containers**: `django_web_dev`, `postgres_dev`, `redis_dev`
- **Separate volumes**: `postgres_data_dev`, `media_dev`
- **Separate ports**: Web exposed on `8010:8000` (internal 8000, external 8010)
- **Separate environment file**: `.env.dev`

## Files Created

1. `docker-compose.dev.yml` - Dev Docker Compose configuration
2. `.env.dev` - Dev environment variables
3. `nginx-dev.conf` - Nginx server block for dev.eeveeit.uk

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
- **Production**: `postgres` database, user `postgres`
- **Dev**: `betterfleets_dev` database, user `dev_user`, password `dev_secure_password`

### Volumes
- **Production**: `postgres_data`, media directory
- **Dev**: `postgres_data_dev`, `media_dev` volume

### Container Names
- **Production**: `django_web`, `postgres`, `redis`
- **Dev**: `django_web_dev`, `postgres_dev`, `redis_dev`

### Ports
- **Production**: Web on `8000:8000`
- **Dev**: Web on `8010:8000`

### Environment Variables
- **Production**: Uses `.env`
- **Dev**: Uses `.env.dev` with `DEBUG=1` and dev-specific settings

## Accessing the Dev Environment

- **Direct access**: http://localhost:8010
- **Via Nginx**: http://dev.eeveeit.uk (after nginx configuration)
- **Django admin**: http://dev.eeveeit.uk/admin (after creating superuser)

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
