# Better Tracking

This directory contains operator-specific vehicle tracking containers. Each operator has their own dedicated container with custom transformation logic and data mapping.

## Structure

```
bettertracking/
  RF/           # Red Funnel (NOC: RF)
    docker-compose.yml
    Dockerfile
    import_redfunnel.py
    README.md
  start.sh      # Script to start all containers
```

## Adding a New Operator

When adding a new operator:

1. Create a new subdirectory with the operator's NOC code
2. Create a `docker-compose.yml` for that operator
3. Create a `Dockerfile` for that operator
4. Create an import script with operator-specific logic
5. Create a `README.md` documenting the transformation and mapping
6. Add the operator to `start.sh`
7. **IMPORTANT**: Do not reuse transformation logic from other operators

## Starting All Containers

### Option 1: Using the start script (recommended)
```bash
cd bettertracking
./start.sh
```

### Option 2: Using docker compose profile
```bash
# From the project root
docker compose --profile bettertracking run --rm bettertracking
```

### Option 3: Starting individual containers
```bash
cd bettertracking/RF
docker compose up -d
```

## Stopping Containers

```bash
cd bettertracking/RF
docker compose down
```

## Viewing Logs

```bash
cd bettertracking/RF
docker compose logs -f
```

## Important Notes

- Each operator has their own coordinate system and data format
- Transformation logic is operator-specific and must not be reused
- Container names should be the operator's NOC code
- All containers use host networking to connect to the existing database and Redis
- Vehicles will appear on the map via the `/vehicles.json` endpoint once imported
