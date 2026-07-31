# Passkey/WebAuthn Authentication Setup

This document describes the passkey (WebAuthn/FIDO2) authentication implementation in BetterFleet using django-allauth's built-in WebAuthn support.

## Overview

Passkey authentication allows users to sign in without passwords using biometric authentication (fingerprint, face recognition) or a PIN. This implementation uses django-allauth's built-in WebAuthn/MFA support.

## Installation

WebAuthn support is included in django-allauth, which is already a dependency of the project. No additional packages need to be installed.

## Configuration

The following environment variables can be configured in your `.env` file. For compatibility, both `WEBAUTHN_*` and `FIDO2_*` prefixes are supported:

- `WEBAUTHN_RP_ID` or `FIDO2_RP_ID` - The relying party ID (default: `localhost`). For production, this should be your domain (e.g., `eeveeit.uk`).
- `WEBAUTHN_RP_NAME` or `FIDO2_RP_NAME` - The relying party name (default: `BetterFleet`).
- `WEBAUTHN_RP_ORIGINS` or `FIDO2_RP_ORIGINS` - Comma-separated list of allowed origins (default: `http://localhost:8000`). For production, set this to `https://yourdomain.com`.

### Example Production Configuration

```bash
FIDO2_RP_ID=eeveeit.uk
FIDO2_RP_NAME=BetterFleet
FIDO2_RP_ORIGINS=https://eeveeit.uk
```

Or using the WEBAUTHN prefix:

```bash
WEBAUTHN_RP_ID=eeveeit.uk
WEBAUTHN_RP_NAME=BetterFleet
WEBAUTHN_RP_ORIGINS=https://eeveeit.uk
```

## Database Migrations

After configuring the settings, run migrations to create the WebAuthn tables:

```bash
python manage.py migrate
```

This will create the necessary tables for django-allauth's WebAuthn support.

## Usage

### Enabling WebAuthn for Users

1. Users must be logged in to enable WebAuthn
2. Navigate to Account Dashboard → Two-Factor Authentication
3. Follow the prompts to add a WebAuthn authenticator
4. The user will be guided through the browser's WebAuthn registration process

### Signing In with WebAuthn

Once WebAuthn is enabled, users can use their registered authenticators during the login process. django-allauth will prompt for WebAuthn authentication as part of the MFA flow.

### Managing Authenticators

Users can view and manage their registered WebAuthn authenticators from the Two-Factor Authentication page in their account dashboard.

## URLs

django-allauth provides the following URL patterns for WebAuthn:

- `/accounts/2fa/` - Two-Factor authentication overview
- `/accounts/2fa/webauthn/` - WebAuthn-specific management
- `/accounts/2fa/webauthn/add/` - Add a new WebAuthn authenticator
- `/accounts/2fa/webauthn/<id>/remove/` - Remove a WebAuthn authenticator

## Implementation Details

### Apps Added

The following apps have been added to `INSTALLED_APPS`:
- `allauth.mfa` - Multi-factor authentication support
- `allauth.mfa.webauthn` - WebAuthn-specific MFA support

### Settings

The following settings have been configured:
- `ALLAUTH_WEBAUTHN_RP_ID` - Relying party ID
- `ALLAUTH_WEBAUTHN_RP_NAME` - Relying party name
- `ALLAUTH_WEBAUTHN_RP_ORIGINS` - Allowed origins

### Security Considerations

- Passkeys are more secure than passwords as they never leave the user's device
- django-allauth handles all WebAuthn operations securely
- Session-based challenges prevent replay attacks
- Proper attestation and verification are handled by the library

## Browser Support

Passkeys are supported in modern browsers:
- Chrome 67+
- Safari 13+
- Firefox 60+
- Edge 18+

## Troubleshooting

### HTTPS Requirement

Passkeys require HTTPS in production. The browser will block passkey registration/authentication on non-secure origins (except localhost).

### Origin Mismatch

If you encounter origin errors, ensure `ALLAUTH_WEBAUTHN_RP_ID` and `ALLAUTH_WEBAUTHN_RP_ORIGINS` are correctly configured for your domain.

### Device Compatibility

Some older devices may not support passkeys. Users should be provided with alternative authentication methods (password, social login, TOTP) as fallbacks.

### MFA Configuration

Ensure that MFA is properly configured in your django-allauth settings. Users may need to have MFA enabled in their account settings to use WebAuthn.
