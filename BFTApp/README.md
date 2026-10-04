# BFT App - BetterFleets Tracking

Native mobile application for tracking vehicle journeys on the BetterFleets platform.

## Features

- **Authentication**: Sign in with BetterFleets account using Clerk
- **Permission Checking**: Only users with Overland permission can access tracking
- **Three Tracking Modes**:
  - Unscheduled: Select vehicle, select stops on map, create journey
  - Scheduled Trip: Select operator, service, starting stop, trip from departures
  - Tracking Only: Route number, destination, vehicle only
- **Vehicle Selection**: Search existing vehicles or create new ones via ticket machine code
- **Map-Based Stop Selection**: Select stops on map with reordering support
- **Route Generation**: OSRM-based route snapping between stops
- **Active Tracking**: Live position, travelled path, stops, planned route
- **Capacity Tracking**: Optional passenger count tracking (+5, +1, 0, -1, -5)
- **Background Location**: Continues tracking when app is backgrounded or device is locked
- **Configurable Interval**: Default 30-second transmission interval

## Setup

### Prerequisites

- Node.js 18+
- Expo CLI: `npm install -g expo-cli`
- EAS CLI: `npm install -g eas-cli`
- BetterFleets backend running

### Installation

```bash
cd BFTApp
npm install --legacy-peer-deps
```

### Environment Variables

Create `.env` file (see `.env.example`):
```
EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_clerk_key_here
EXPO_PUBLIC_API_URL=http://localhost:8000
```

### Running

```bash
# Start development server
npm start

# Run on Android
npm run android

# Run on iOS (macOS only)
npm run ios
```

## Building

### Android APK

Using GitHub Actions (recommended):
1. Push to `main` branch
2. APK will be built automatically and available as artifact

Manual:
```bash
eas build --platform android --profile production
```

### iOS IPA

Using GitHub Actions (recommended):
1. Push to `main` branch
2. IPA will be built automatically and available as artifact

Manual (requires macOS):
```bash
eas build --platform ios --profile production
```

## Architecture

- **Framework**: React Native with Expo
- **Navigation**: Expo Router
- **Authentication**: Clerk React Native SDK
- **Backend Integration**: BetterFleets API
- **Location**: Expo Location with background support
- **Storage**: Expo Secure Store for API keys

## Color Scheme

Using BetterFleets colors:
- Brand: `#ffff9e` (yellow)
- Text: `#222` (light mode)
- Link: `#54c`

## API Endpoints

- `GET /api/users/permissions/` - Check Overland permission
- `GET /api/vehicles/` - Vehicle search
- `GET /api/stops/` - Stop data
- `POST /overland/{uuid}/` - Tracking data ingestion

## Development

```bash
# Type check
npm run typecheck

# Lint
npm run lint
```

## License

Part of the BetterFleets project.
