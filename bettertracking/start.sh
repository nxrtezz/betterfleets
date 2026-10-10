#!/bin/bash

# Start script for Better Tracking containers
# This script starts all tracking containers using the main docker-compose stack
# Note: Containers use the main stack's database and Redis

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Starting Better Tracking containers..."

cd "$PROJECT_DIR"

# Start tracking containers (BODS AVL and RF)
docker compose --profile tracking up -d

echo "Better Tracking containers started"
echo "Use 'docker compose logs -f rf' or 'docker compose logs -f bods_avl' to view logs"
