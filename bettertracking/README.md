# Better Tracking

This directory contains operator-specific vehicle tracking containers. These are now integrated into the main docker-compose stack using profiles.

## Structure

Tracking commands are implemented as Django management commands in `vehicles/management/commands/`:
- `import_redfunnel.py` - Red Funnel (RF) vehicle tracking
- `import_bod_avl.py` - BODS AVL vehicle tracking

## Starting All Tracking Containers

```bash
cd bettertracking
./start.sh
```

Or directly from the project root:

```bash
docker compose --profile tracking up -d
```

## Starting Individual Containers

```bash
# BODS AVL
docker compose --profile tracking up -d bods_avl

# Red Funnel
docker compose --profile tracking up -d rf
```

## Viewing Logs

```bash
# BODS AVL
docker compose logs -f bods_avl

# Red Funnel
docker compose logs -f rf
```

## Stopping Containers

```bash
docker compose --profile tracking down
```

## Important Notes

- Each operator has their own coordinate system and data format
- Transformation logic is operator-specific and must not be reused
- All containers use the main stack's database and Redis
- Vehicles will appear on the map via the `/vehicles.json` endpoint once imported
