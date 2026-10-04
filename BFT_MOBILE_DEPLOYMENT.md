# BFT Mobile App - Setup and Deployment

## Backend Changes Completed

The following backend changes have been made to support the mobile app:

### 1. Capacity Fields Added to OverlandSubscription
- Added `capacity_current`, `capacity_max`, `capacity_enabled` fields
- Migration: `fleet/migrations/0011_overlandsubscription_capacity.py`

### 2. Updated overland_ingest Endpoint
- Modified to accept capacity data in tracking payload
- File: `fleet/views.py`

### 3. User Permissions API Endpoint
- Added `GET /api/users/permissions/` endpoint
- File: `api/views.py`

### 4. Removed Web Overland Endpoint
- Commented out `/overland` web generator
- Commented out `/overland.json` deprecated endpoint
- Preserved `/overland/<uuid>` ingest endpoint for API compatibility
- File: `busstops/urls.py`

## Mobile App Created

The mobile app has been created in the `BFTApp/` directory with:

### Project Structure
- **Framework**: React Native with Expo SDK 53
- **Navigation**: Expo Router with file-based routing
- **Authentication**: Clerk React Native SDK
- **Location**: Expo Location with background support
- **Secure Storage**: Expo Secure Store for API keys

### Files Created
- `src/app/_layout.tsx` - Root layout with Clerk provider
- `src/app/(tabs)/_layout.tsx` - Tab layout with permission checking
- `src/app/(tabs)/index.tsx` - Tracking screen (placeholder)
- `src/app/(tabs)/vehicles.tsx` - Vehicles screen (placeholder)
- `src/app/(tabs)/settings.tsx` - Settings screen (placeholder)
- `src/app/sign-in.tsx` - Sign-in screen with Clerk
- `src/app/access-denied.tsx` - Access denied screen
- `app.json` - Expo configuration with location permissions
- `eas.json` - EAS build configuration
- `.github/workflows/build-android.yml` - GitHub Actions for Android APK
- `.github/workflows/build-ios.yml` - GitHub Actions for iOS IPA
- `README.md` - Project documentation
- `.env.example` - Environment variables template

### GitHub Actions Workflows

Two workflows have been created for automated building:

#### Android APK Build
- Triggered on push to `main` branch or manual dispatch
- Builds Android APK using EAS
- Uploads APK as GitHub artifact

#### iOS IPA Build
- Triggered on push to `main` branch or manual dispatch
- Builds iOS IPA using EAS
- Uploads IPA as GitHub artifact

## Next Steps

### 1. Run Database Migration
```bash
cd betterfleets
python manage.py migrate fleet
```

### 2. Create GitHub Repository
You need to create a new GitHub repository for the mobile app:

1. Go to GitHub and create a new repository (e.g., `betterfleets/bft-app`)
2. Do NOT initialize with README, .gitignore, or license
3. Copy the repository URL

### 3. Push Mobile App to GitHub
```bash
cd BFTApp
git remote add origin https://github.com/YOUR_USERNAME/bft-app.git
git branch -M main
git push -u origin main
```

### 4. Configure GitHub Secrets
In your GitHub repository settings, add the following secrets:

**Required for EAS Build:**
- `EXPO_TOKEN` - Your Expo account token (get from https://expo.dev/accounts/tokens)

**Required for the App:**
- `EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY` - Your Clerk publishable key
- `EXPO_PUBLIC_API_URL` - Your BetterFleets API URL (e.g., https://betterfleets.org)

### 5. Configure EAS
```bash
cd BFTApp
npx eas-cli login
npx eas-cli build:configure
```

### 6. Install Dependencies (if not already done)
```bash
cd BFTApp
npm install --legacy-peer-deps
```

### 7. Test the App
```bash
cd BFTApp
npm start
```

### 8. Build APK/IPA
Push to the `main` branch to trigger automatic builds, or manually trigger workflows from GitHub Actions tab.

## Notes

- The mobile app is a basic skeleton with placeholder screens
- Full implementation of tracking modes, maps, and background location needs to be completed
- The backend is ready to accept tracking data with capacity information
- Permission checking endpoint is available at `/api/users/permissions/`
- Tracking data should be sent to `/overland/{uuid}/` endpoint with the format documented in `BFT_MOBILE_APP_SETUP.md`

## Architecture Decisions

- **Expo Router**: File-based routing in `src/app/` directory
- **Clerk Authentication**: Secure token storage with Expo Secure Store
- **EAS Build**: Cloud-based building for iOS and Android
- **GitHub Actions**: Automated CI/CD for APK and IPA generation
- **Expo SDK 53**: Chosen for compatibility with Clerk and other dependencies

## Dependencies

The app uses `--legacy-peer-deps` to install due to dependency conflicts between Expo 53, React Native 0.76.6, and Clerk. This is a known issue with the current ecosystem and does not affect functionality.
