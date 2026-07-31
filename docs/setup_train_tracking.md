# Train Tracking Setup Guide

Your BetterFleet system already has comprehensive train tracking capabilities. Here's how to enable it:

## 1. Configure The Data Source

The train service supports two modes:

- `TRAIN_SOURCE=push-port` consumes Darwin Push Port JSON from Kafka.
- `TRAIN_SOURCE=ldb` polls OpenLDBWS as a fallback.

For Push Port, set the Kafka values in `services/darwin-trains/.env` or your
deployment secret store:

```bash
TRAIN_SOURCE=push-port
DARWIN_KAFKA_TOPIC=prod-1010-Darwin-Train-Information-Push-Port-IIII2_0-JSON
DARWIN_KAFKA_BROKERS=pkc-z3p1v0.europe-west2.gcp.confluent.cloud:9092
DARWIN_KAFKA_CLIENT_ID=betterfleet-darwin-trains
DARWIN_KAFKA_GROUP_ID=...
DARWIN_KAFKA_USERNAME=...
DARWIN_KAFKA_PASSWORD=...
DARWIN_KAFKA_SASL_MECHANISM=plain
DARWIN_KAFKA_SSL=true
```

Trains are emitted through `/trains.json` using the same vehicle marker shape as
buses. The service extracts the train fleet number from the Darwin JSON payload,
looks up the matching vehicle through `VEHICLES_API_URL`, and uses that vehicle's
livery CSS for the marker. For example, `444045` will match the existing class 444
vehicle record if it exists in the local vehicle database.

```bash
VEHICLES_API_URL=http://127.0.0.1:8000/api/vehicles/
VEHICLE_URL_BASE=http://127.0.0.1:8000
```

The Push Port feed does not always contain coordinates. When no coordinates are
present, the service falls back to CRS/TIPLOC-like location codes and maps those
through `GTFS_STOPS_PATH`.

## 2. Get National Rail API Access For LDB Fallback

1. Register at: https://realtime.nationalrail.co.uk/OpenLDBWSRegistration/Registration
2. You'll receive an access token via email
3. This token allows access to the Darwin API for real-time train data

## 3. Configure Darwin Service

Copy the environment file and add your credentials:

```bash
cd services/darwin-trains
cp .env.example .env
```

Edit `.env` and set:
```bash
DARWIN_ACCESS_TOKEN=your_actual_nr_access_token
```

## 4. Install Dependencies

```bash
cd services/darwin-trains
npm install
```

## 5. Start Darwin Service

```bash
cd services/darwin-trains
npm start
```

This will start a Node.js service on port 8765 that:
- Consumes Darwin Push Port Kafka or polls National Rail for train data
- Interpolates train positions along routes
- Serves data at `http://localhost:8765/trains.json`

## 6. Configure Django

Set the environment variable:
```bash
export DARWIN_TRAINS_NODE_URL="http://localhost:8765"
```

Or add to your Django environment settings.

## 7. Access Train Map

Visit: `http://localhost:8000/map/trains`

## Features Already Available

- **Real-time train positions** with smooth animations
- **Route filtering** by operator/service
- **Clustering** for performance with many trains
- **Click interactions** to view train details
- **Responsive design** with mobile support
- **Bounding box filtering** for efficient data loading

## Customization Options

### Monitor Different Stations
Edit `DARWIN_CRS_LIST` in the `.env` file to monitor different stations:
```bash
DARWIN_CRS_LIST=EUS,PAD,KGX,MAN,BHM,EDI,GLC
```

### Performance Tuning
- `DARWIN_NUM_ROWS`: Services to fetch per station (default: 15)
- `DARWIN_TIME_WINDOW`: Time window in minutes (default: 120)
- `DARWIN_MAX_SERVICE_DETAILS`: Max services to process (default: 100)
- `DARWIN_POLL_MS`: Poll interval in milliseconds (default: 12000)

## GTFS Data

The system includes a basic UK rail stations file (`gtfs_uk_rail_stops.txt`). For more accurate positioning, you can:
1. Download official UK rail GTFS data
2. Update the `GTFS_STOPS_PATH` to point to your file
3. Ensure stations have CRS codes in `stop_code` field

## Alternative: GTFS-RT Feed

If you have access to GTFS-RT vehicle position feeds, you can use the Python backend instead:
1. Set `DARWIN_TRAINS_NODE_URL=""` (empty)
2. Configure GTFSR settings in Django
3. The system will use `vehicles/train_gtfsr.py` instead

## Troubleshooting

- **No trains showing**: Check Darwin service is running and API token is valid
- **Incorrect positions**: Verify GTFS stops data has correct coordinates
- **Performance issues**: Reduce `DARWIN_MAX_SERVICE_DETAILS` or station list

## Architecture

```
Frontend (TrainMap.tsx) 
    requests -> Django (/trains.json)
    proxies -> Darwin Service (/trains.json)
    polls -> National Rail (Darwin API)
```

The system is production-ready with proper error handling, caching, and performance optimizations.
