#!/bin/bash

# Start script for Better Tracking containers
# This script starts all operator-specific tracking containers
# Note: These containers use host networking to connect to the existing
# database and Redis instances from the main BetterFleet stack

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting Better Tracking containers..."

# Check if operator directories exist
if [ ! -d "$SCRIPT_DIR/RF" ]; then
    echo "Error: RF directory not found"
    exit 1
fi

# Start RF (Red Funnel) container
echo "Starting RF (Red Funnel) container..."
cd "$SCRIPT_DIR/RF"
docker compose up -d

echo "All Better Tracking containers started"
echo "Note: Containers use host networking to connect to existing database/Redis"
