# BFT Mobile App - BetterFleets Tracking

## Overview

The BFT (BetterFleets Tracking) mobile app is a native mobile application for tracking vehicle journeys. This document provides setup instructions and architecture decisions.

## Architecture Decisions

### Framework: React Native with Expo

After analysis of the project, React Native with Expo was chosen because:
- The existing frontend uses React + TypeScript
- Clerk has excellent React Native SDK support
- Shared components and patterns can be reused
- Cross-platform support for iOS and Android
- Native modules for background location
- Follows the project's existing React patterns

### Tracking Data Submission

The app extends the existing Overland protocol rather than creating a new push API:
- The existing `/overland/<uuid>` endpoint already works correctly
- It creates VehicleJourney records properly
- It stores location data in Redis
- It integrates with vehicles.json
- The OverlandSubscription model has the required fields
- Capacity field support has been added

## Backend Changes Completed

### 1. Capacity Fields Added to OverlandSubscription

**File**: `fleet/models.py`

Added three new fields to the `OverlandSubscription` model:
- `capacity_current`: Current passenger count (PositiveIntegerField, default 0)
- `capacity_max`: Maximum capacity (PositiveIntegerField, default 0)
- `capacity_enabled`: Whether capacity tracking is enabled (BooleanField, default False)

**Migration**: `fleet/migrations/0011_overlandsubscription_capacity.py`

### 2. Updated overland_ingest Endpoint

**File**: `fleet/views.py`

The `/overland/<uuid>` endpoint now accepts capacity data in the payload properties:
- `capacity_current`: Current passenger count
- `capacity_max`: Maximum capacity
- `capacity_enabled`: Boolean to enable/disable capacity tracking

### 3. User Permissions API Endpoint

**File**: `api/views.py`

Added a new endpoint `GET /api/users/permissions/` that returns:
```json
{
  "overland": true/false
}
```

This allows the mobile app to check if the authenticated user has the `fleet.use_overland` permission.

### 4. Removed Web Overland Endpoints

**File**: `busstops/urls.py`

Commented out the web Overland generator endpoint (`/overland`) and the deprecated `overland.json` endpoint. The tracking functionality is now provided through:
- The mobile app (new)
- The existing `/overland/<uuid>` ingest endpoint (preserved for API compatibility)
- Integration with vehicles.json (preserved)

## Mobile App Setup Instructions

### Prerequisites

- Node.js 18+ and npm
- For iOS: macOS with Xcode
- For Android: Android Studio with SDK
- Expo CLI: `npm install -g expo-cli`
- BetterFleets backend running

### Project Setup

```bash
# Create new Expo project with TypeScript
npx create-expo-app@latest BFTApp --template blank-typescript

# Navigate to project
cd BFTApp

# Install dependencies
npm install @clerk/expo @react-navigation/native @react-navigation/bottom-tabs react-native-maps expo-location expo-task-manager expo-background-fetch expo-secure-store expo-device @react-native-async-storage/async-storage react-native-safe-area-context react-native-screens

# Install iOS pods (if on macOS)
cd ios && pod install && cd ..
```

### Environment Configuration

Create `.env` file:
```
EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_clerk_key_here
EXPO_PUBLIC_API_URL=http://localhost:8000
```

### App Configuration

**app.json** should include:
- Proper bundle identifiers
- Location permissions for iOS and Android
- Background location permissions
- Expo plugins for location, task manager, background fetch, secure store

### Key Screens to Implement

1. **Authentication Screen** (Clerk)
   - Sign in with BetterFleets account
   - Use Clerk's React Native SDK

2. **Permission Check**
   - Call `/api/users/permissions/` endpoint
   - Show AccessDeniedScreen if no Overland permission

3. **Three-Tab Navigation**
   - Tracking tab (primary)
   - Vehicles tab (search)
   - Settings tab (configuration)

4. **Tracking Tab - Three Modes**
   - Unscheduled: Select vehicle, select stops on map, create journey
   - Scheduled Trip: Select operator, service, starting stop, trip from departures
   - Tracking Only: Route number, destination, vehicle only

5. **Vehicle Selection**
   - Current Vehicle: Search existing BetterFleets vehicles
   - New Vehicle: Enter ticket machine code, create new vehicle record

6. **Map-Based Stop Selection**
   - Display available stops on map
   - Tap to add to ordered list
   - Support reordering
   - Hidden waypoint stops for OSRM routing
   - Route preview with snapped OSRM geometry

7. **Active Tracking View**
   - Service/route number and destination at top
   - Map showing:
     - Current position (centred)
     - Travelled path
     - Planned route
     - Stops being served
   - Scrollable stop list below map
   - Passed stops greyed out (proximity threshold)
   - Controls: Stop Tracking, Pause Tracking, Set Capacity
   - Capacity interface: +5, +1, 0, -1, -5
   - Last location sent indicator

8. **Background Location**
   - Continue tracking when app is backgrounded
   - Continue tracking when device is locked
   - Follow iOS and Android platform requirements
   - Battery-conscious implementation

9. **Vehicle Search**
   - Search by fleet number, registration, vehicle code
   - Show vehicle details
   - Display current/last journey information

10. **Settings**
    - Location transmission interval (default 30s, configurable)
    - Account/logout controls
    - Location/background tracking settings

### API Integration

The mobile app will use:

1. **Authentication**: Clerk React Native SDK
2. **Permissions**: `GET /api/users/permissions/`
3. **Vehicles**: `GET /api/vehicles/` (with filters)
4. **Vehicle Details**: `GET /api/vehicles/{id}/`
5. **Stops**: `GET /api/stops/` (with filters)
6. **Trips**: `GET /api/trips/` (with filters)
7. **Services**: `GET /api/services/` (with filters)
8. **Operators**: `GET /api/operators/` (with filters)
9. **Vehicle Journeys**: `GET /api/vehiclejourneys/` (with filters)
10. **Tracking Ingest**: `POST /overland/{uuid}/` with location payload

### Tracking Payload Format

```json
{
  "locations": [
    {
      "geometry": {
        "coordinates": [longitude, latitude]
      },
      "properties": {
        "timestamp": "2026-10-04T20:00:00Z",
        "course": 45,
        "capacity_current": 23,
        "capacity_max": 50,
        "capacity_enabled": true
      }
    }
  ]
}
```

### Color Scheme

Use BetterFleets existing colors:
- Brand color: `#ffff9e` (yellow)
- Brand color darker: `#de8`
- Text color: `#222` (light mode), `#fff` (dark mode)
- Link color: `#54c`
- Background: `#fff` (light mode), `#222` (dark mode)

### Design Principles

- Simple, clean, operational interface
- Lightweight - avoid unnecessary animations
- Large touch targets
- Accessible with VoiceOver and TalkBack
- Consistent with BetterFleets web design language

## Building the App

### iOS
```bash
npm run ios
# Or build for distribution:
eas build --platform ios
```

### Android
```bash
npm run android
# Or build APK:
eas build --platform android
```

## Next Steps

1. Set up the React Native project following the instructions above
2. Implement the screens in the order listed
3. Test authentication flow with Clerk
4. Test permission checking
5. Test vehicle selection and search
6. Test tracking modes
7. Test background location
8. Test capacity tracking
9. Test API integration
10. Build and test on physical devices

## Notes

- The web Overland generator endpoint has been removed (commented out in URLs)
- The `/overland/<uuid>` ingest endpoint is preserved for API compatibility
- Capacity data is optional in the tracking payload
- The app should handle network loss gracefully
- Location transmission interval is configurable (default 30s)
- The app must not keep the screen awake during tracking
