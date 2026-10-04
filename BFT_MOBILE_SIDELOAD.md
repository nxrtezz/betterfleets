# BFT Mobile App - Sideloading Guide

This guide covers sideloading the BFT mobile app for iOS and Android without App Store/Play Store approval.

## What is Sideloading?

Sideloading means installing apps directly on your device without going through the official app stores. This is perfect for:
- Testing your own apps
- Distributing apps to a small team
- Avoiding App Store approval processes
- Using free Apple ID instead of paid developer account

---

## Connecting GitHub to Expo (One-Time Setup)

### Step 1: Create an Expo Account

1. Go to https://expo.dev
2. Click "Sign up"
3. Sign up with GitHub (recommended) or email
4. Verify your email address

### Step 2: Create an Expo Project

1. After signing in, you'll be prompted to create a project
2. Click "Create a new project"
3. Give it a name (e.g., "betterfleets-bft")
4. Choose "Blank" template
5. This creates the project in Expo's cloud

### Step 3: Link Your GitHub Repository

1. In Expo dashboard, go to your project
2. Click "Settings" → "General"
3. Look for "GitHub Integration" or "Source Control"
4. Click "Connect GitHub"
5. Authorize Expo to access your GitHub account
6. Select your repository: `nxrtezz/betterfleets`
7. Select the branch: `main`
8. Expo will now automatically track your builds

### Step 4: Get Your Expo Token

1. Go to https://expo.dev/accounts/[your-username]/tokens
2. Click "Create new token"
3. Give it a name (e.g., "GitHub Actions")
4. Copy the token - **you won't see it again**

### Step 5: Add Expo Token to GitHub Secrets

1. Go to your GitHub repository: https://github.com/nxrtezz/betterfleets
2. Click "Settings" → "Secrets and variables" → "Actions"
3. Click "New repository secret"
4. Name: `EXPO_TOKEN`
5. Value: Paste the token from Step 4
6. Click "Add secret"

### Step 6: Configure EAS Build

1. Open terminal/command prompt
2. Navigate to the BFTApp directory:
   ```bash
   cd betterfleets/BFTApp
   ```
3. Login to EAS:
   ```bash
   npx eas-cli login
   ```
4. This will open a browser - log in with your Expo account
5. Configure the project:
   ```bash
   npx eas-cli build:configure
   ```
6. Answer the prompts:
   - Would you like to automatically create an EAS project? **Yes**
   - Generate a new Android Keystore? **Yes** (or create your own)
   - Generate a new iOS provisioning profile? **Yes** (uses your free Apple ID)

---

## Android Sideloading

### Method 1: Direct Installation (Easiest)

1. **Enable Unknown Sources** on your Android device:
   - Go to Settings → Security
   - Enable "Install from unknown sources" or "Allow from this source"
   - Select your file manager/browser

2. **Download the APK**:
   - Go to GitHub Actions: https://github.com/nxrtezz/betterfleets/actions
   - Find the latest "Build Android APK" workflow run
   - Download the `android-apk` artifact
   - Extract the ZIP file
   - Find the `.apk` file

3. **Install**:
   - Transfer the APK to your Android device (USB, email, cloud storage)
   - Open the APK file on your device
   - Tap "Install"
   - Done!

### Method 2: ADB (Advanced)

If you have Android SDK installed:

```bash
adb install BFTApp.apk
```

---

## iOS Sideloading

iOS requires more steps because of Apple's restrictions. You'll need a sideloading tool.

### Option 1: AltStore (Recommended for Mac + iPhone)

**Requirements**:
- Mac computer
- iPhone/iPad
- Both devices on same Wi-Fi
- Free Apple ID

**Steps**:

1. **Install AltServer on your Mac**:
   - Download from https://altstore.io
   - Install AltServer (follow instructions on website)
   - Open AltServer in menu bar

2. **Install AltStore on your iPhone**:
   - Download AltStore from https://altstore.io on your iPhone
   - Follow the on-screen instructions to install
   - Your Mac's AltServer will appear - select it
   - Enter your Apple ID and password

3. **Download the IPA**:
   - Go to GitHub Actions: https://github.com/nxrtezz/betterfleets/actions
   - Find the latest "Build iOS IPA" workflow run
   - Download the `ios-ipa` artifact
   - Extract the ZIP file
   - Find the `.ipa` file

4. **Sideload with AltStore**:
   - Open AltStore on your iPhone
   - Tap the "+" icon
   - Select the `.ipa` file (from Files app or cloud storage)
   - Enter your Apple ID and password
   - Wait for installation

5. **Refresh App (Every 7 days)**:
   - Free Apple ID apps expire in 7 days
   - Open AltStore periodically to refresh
   - Tap "My Apps" → tap the app → "Refresh"

### Option 2: SideStore (No Mac Required)

**Requirements**:
- Windows or Linux computer
- iPhone/iPad
- Free Apple ID

**Steps**:

1. **Download SideStore**:
   - Go to https://sidestore.io
   - Download the SideStore companion app for your computer

2. **Install SideStore on iPhone**:
   - Follow the instructions on the SideStore website
   - This involves a more complex initial setup
   - You'll need to trust a developer certificate

3. **Sideload with SideStore**:
   - Open SideStore on your computer
   - Connect your iPhone via USB
   - Drag and drop the `.ipa` file
   - Enter your Apple ID
   - Install

### Option 3: Sideloadly (Windows/Mac)

**Requirements**:
- Windows or Mac computer
- iPhone/iPad
- Free Apple ID

**Steps**:

1. **Download Sideloadly**:
   - Go to https://sideloadly.io
   - Download for Windows or Mac

2. **Connect your iPhone**:
   - Connect iPhone to computer via USB
   - Trust the computer on your iPhone

3. **Install with Sideloadly**:
   - Open Sideloadly
   - Select your device
   - Select the `.ipa` file
   - Enter your Apple ID and password
   - Click "Start"
   - Wait for installation

---

## GitHub Actions Builds

### Triggering Builds

**Automatic**:
- Push to `main` branch automatically triggers both Android and iOS builds

**Manual**:
1. Go to https://github.com/nxrtezz/betterfleets/actions
2. Click "Build Android APK" or "Build iOS IPA"
3. Click "Run workflow"
4. Select branch: `main`
5. Click "Run workflow"

### Downloading Builds

1. Go to https://github.com/nxrtezz/betterfleets/actions
2. Click on the workflow run you want
3. Scroll down to "Artifacts"
4. Download:
   - `android-apk` for Android
   - `ios-ipa` for iOS
5. Extract the ZIP file
6. Find the `.apk` or `.ipa` file

---

## Important Notes

### Android
- APK files work on any Android device
- No expiration
- No Google Play account needed
- Enable "Unknown Sources" in settings

### iOS
- IPA files expire in 7 days (free Apple ID)
- Need to refresh every 7 days via sideloading tool
- No Apple Developer account needed ($99/year saved)
- No App Store approval needed

### Updates
When you update the app:
1. Push changes to GitHub
2. GitHub Actions builds new APK/IPA
3. Download and sideload the new version
4. Overwrites the old version

---

## Troubleshooting

### Android "Install Blocked"
- Go to Settings → Security → Unknown Sources
- Enable it for your file manager

### iOS "Untrusted Developer"
- Go to Settings → General → VPN & Device Management
- Find your Apple ID
- Tap "Trust"

### AltStore/AltServer Connection Issues
- Ensure both devices on same Wi-Fi
- Restart AltServer on Mac
- Reinstall AltStore on iPhone

### Build Failures
- Check GitHub Actions logs for errors
- Ensure `EXPO_TOKEN` is set correctly
- Ensure EAS is configured: `npx eas-cli build:configure`

---

## Next Steps

Once you've set up Expo and configured GitHub Actions:

1. Trigger a test build (manual workflow dispatch)
2. Download the APK/IPA
3. Sideload to your device
4. Test the app
5. Make changes, push to GitHub, rebuild, and repeat
