#!/bin/bash

# BetterFleets Production Startup Script
# This script starts all necessary services for production deployment

set -e

echo "Starting BetterFleets production services..."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Run database migrations
echo "Running database migrations..."
python manage.py migrate --noinput

# Start Gunicorn (Django application server)
echo "Starting Gunicorn..."
gunicorn buses.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --worker-class sync \
    --worker-tmp-dir /dev/shm \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --log-level info &

# Start Discord bot
echo "Starting Discord bot..."
python manage.py run_discord_bot &

# Start Celery worker for background tasks (if using Celery)
# echo "Starting Celery worker..."
# celery -A buses worker -l info &

# Start Celery beat for scheduled tasks (if using Celery)
# echo "Starting Celery beat..."
# celery -A buses beat -l info &

echo "All services started successfully!"
echo "Gunicorn running on port 8000"
echo "Discord bot running in background"
echo "Press Ctrl+C to stop all services"

# Wait for all background processes
wait
