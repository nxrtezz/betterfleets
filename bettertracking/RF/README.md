# Red Funnel (RF) Vehicle Tracking

**THIS CONTAINER AND THESE INSTRUCTIONS ARE ONLY FOR THIS OPERATOR (Red Funnel, NOC: RF).**

Do not reuse this code for other operators. Each operator will have their own dedicated container with their own specific transformation logic and data mapping.

## Overview

This container fetches live vehicle data from Red Funnel's AIS endpoint and converts it to the BetterFleet format for display on the map.

## Endpoint

- **URL**: `http://ais.redfunnel.co.uk/home/boats`
- **Format**: JSON array of vehicle objects

## Coordinate Transformation

Red Funnel provides x,y coordinates in a custom map projection. This script converts them to WGS84 lat/long using a linear transformation.

### Reference Points

| Red Funnel x,y | WGS84 lat,lon | Location |
|----------------|---------------|----------|
| 807, 132 | 50.894394558883086, -1.4053852469929418 | Red Jet 7 |
| 900, 708 | 50.759230392116166, -1.2904174657707368 | East Cowes Terminal |

### Transformation Formula

```python
lat = -0.00023457701834389 * y + 50.925358725304086
lon = 0.00123588162583086 * x - 2.4027361037108453
```

Calculated as:
```python
LAT_SCALE = (lat2 - lat1) / (y2 - y1)
LAT_OFFSET = lat1 - LAT_SCALE * y1
LON_SCALE = (lon2 - lon1) / (x2 - x1)
LON_OFFSET = lon1 - LON_SCALE * x1
```

**THIS FORMULA IS SPECIFIC TO RED FUNNEL ONLY.**

## Data Mapping

### Vehicle ID Mapping

| Red Funnel ID | Fleet Slug |
|---------------|------------|
| JET7 | RED7 |
| FALC | REDFAL |
| KEST | REDKES |
| EAGL | REDEAG |
| OSPR | REDOSP |

### Class to Route Number

| Class | Route Number |
|-------|--------------|
| high-speed | RedJet |
| ferry | RedFunnel |
| out-of-service | (none) |

### Destination

Extracted from the second line of the `info` array in the label object.

### Heading

Taken from the `rotation` value in the marker object.

### Route Number Display

Route number is hidden when the info array contains:
- "At destination"
- "Not in service"

### Trip/Journey Creation

A new trip and journey is created when the route direction changes:
- Southampton → Isle of Wight
- Isle of Wight → Southampton

## Usage

### Start the container

```bash
cd bettertracking
./start.sh
```

Or start individually:

```bash
cd bettertracking/RF
docker compose up -d
```

### View logs

```bash
cd bettertracking/RF
docker compose logs -f
```

### Stop the container

```bash
cd bettertracking/RF
docker compose down
```

## Operator Details

- **NOC**: RF
- **Name**: Red Funnel
- **Vehicle Mode**: ferry
- **Services**: RedJet (high-speed), RedFunnel (conventional ferry)

## Future Operators

When adding new operators:
1. Create a new subdirectory in `bettertracking/` with the operator's NOC
2. Create a separate `docker-compose.yml` for that operator
3. Implement operator-specific transformation logic
4. Add the operator to `start.sh`
5. **DO NOT** reuse Red Funnel's transformation code
