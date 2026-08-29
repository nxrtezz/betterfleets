# BetterFleets Production Release Test Suite

This directory contains comprehensive test scripts for validating the BetterFleets system before production release.

## Available Test Scripts

1. **test_prod_release.sh** - Bash shell script (Linux/Mac/WSL) - **Primary for Debian servers**
2. **test_prod_release.bat** - Windows batch file
3. **test_prod_release.ps1** - PowerShell script (Windows)

## Configuration

The test scripts are pre-configured to test against:
- **Default**: `https://dev.eeveeit.uk` (Debian deployment environment)

You can override this using the `BASE_URL` environment variable if needed.

## What the Tests Cover

### Phase 1: Basic System Health Checks
- Site accessibility
- Admin panel accessibility
- API site-info endpoint

### Phase 2: API Endpoint Tests (Read Operations)
- Vehicles list endpoint
- Liveries list endpoint
- Vehicle types list endpoint
- Operators list endpoint
- Garages list endpoint
- Services list endpoint
- Trips list endpoint
- Users list endpoint

### Phase 3: Web Interface Tests
- Vehicles page accessibility
- Dashboard accessibility
- Map page accessibility
- Events page accessibility

### Phase 4: User Creation and Authentication
- Test user creation via Django management commands
- User with trusted status and advanced editing permissions
- API key generation for authenticated requests

### Phase 5: API Write Operations (with Authentication)
- Operator creation (authenticated)
- Operator updates (authenticated)
- Vehicle photo logging (authenticated)

### Phase 6: Vehicle Management Tests
- Vehicle detail page error handling
- Vehicle edit page authentication requirements

### Phase 7: Advanced Editing Tests
- Basic fleet export authentication
- Advanced fleet export authentication
- Advanced mode functionality

### Phase 8: Request System Tests
- Vehicle request page accessibility
- Service request page accessibility
- Operator request page accessibility

### Phase 9: Service Request System Tests
- Service requests list authentication
- Service request creation authentication

### Phase 10: Operator and Service Pages
- Operator vehicles page routing
- Service page functionality

### Phase 11: Filter and Search Tests
- API vehicles with filters
- API operators with filters
- API services with filters

### Phase 12: Edge Cases and Error Handling
- Invalid vehicle ID handling
- Invalid operator ID handling
- Malformed JSON handling

### Phase 13: Pagination Tests
- API vehicles pagination
- API operators pagination

### Phase 14: Performance Tests (basic)
- API response time measurements
- Performance threshold validation (< 5000ms for vehicle list)

### Phase 15: Cleanup
- Test data removal
- Test user deletion
- Test operator deletion

## Prerequisites

1. **Django environment** with `python manage.py` commands available
2. **curl** command-line tool for HTTP requests
3. **Running Django server** at the configured URL (default: http://localhost:8000)
4. **Database access** for user creation and cleanup operations

## Configuration

The test scripts can be configured using environment variables:

- `BASE_URL` - The base URL of the application (default: http://localhost:8000)
- `ADMIN_USERNAME` - Admin username for admin panel tests (default: admin)
- `ADMIN_PASSWORD` - Admin password for admin panel tests (default: admin123)

### Example Configuration

```bash
# Linux/Mac/WSL
export BASE_URL="http://localhost:8000"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="your_secure_password"

# Windows PowerShell
$env:BASE_URL = "http://localhost:8000"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "your_secure_password"

# Windows Command Prompt
set BASE_URL=http://localhost:8000
set ADMIN_USERNAME=admin
set ADMIN_PASSWORD=your_secure_password
```

## Usage

### Linux/Mac/WSL (Bash)

```bash
# Make the script executable
chmod +x test_prod_release.sh

# Run the tests
./test_prod_release.sh

# Or with custom configuration
BASE_URL=http://your-server.com ./test_prod_release.sh
```

### Windows (PowerShell)

```powershell
# Run the tests
.\test_prod_release.ps1

# Or with custom configuration
$env:BASE_URL = "http://your-server.com"
.\test_prod_release.ps1
```

### Windows (Command Prompt)

```cmd
# Run the tests
test_prod_release.bat

# Or with custom configuration
set BASE_URL=http://your-server.com
test_prod_release.bat
```

## Expected Output

The test scripts provide color-coded output:

- **[INFO]** - Informational messages (yellow)
- **[PASS]** - Successful tests (green)
- **[FAIL]** - Failed tests (red)
- **[FAIL DETAIL]** - Detailed error information (red)

At the end, you'll see a summary:

```
==========================================
Test Summary
==========================================
Total tests: 45
Passed: 45
Failed: 0
All tests passed!
```

## Error Capture Feature

The test scripts include comprehensive error capture to help you debug issues:

### Automatic Error Logging
- All failed tests are logged with detailed information
- HTTP response bodies and status codes are captured
- Command output and exit codes are recorded
- Exception details and stack traces are saved

### Error Files Generated
- `error_capture_for_chat.txt` - Formatted error summary for sharing
- `test_errors_YYYYMMDD_HHMMSS.log` - Detailed error log with timestamps

### Copy-Paste Error Reporting
When tests fail, the script will display a section marked:

```
============================================
ERROR CAPTURE FOR CHAT
============================================

Copy and paste the content below to get help with fixing errors:

--- START ERROR CAPTURE ---
[Detailed error information]
--- END ERROR CAPTURE ---
```

Simply copy the content between the markers and paste it in chat to get help fixing the issues.

## Test Data Management

The test scripts automatically:

1. Create a test user with unique email (timestamp-based)
2. Generate an API key for authenticated requests
3. Create a test operator for write operation tests
4. Clean up all test data after completion

## Interpreting Results

### All Tests Pass
- System is ready for production release
- All endpoints are functioning correctly
- Authentication and authorization are working
- Error handling is robust

### Some Tests Fail
- Review the failed test messages
- Check server logs for additional details
- Verify configuration and environment
- Ensure database is accessible
- Check that the Django server is running

### Common Issues

1. **Connection refused** - Ensure Django server is running
2. **Authentication failures** - Check user creation and API key generation
3. **Database errors** - Verify database connectivity and permissions
4. **Timeout errors** - Check server performance and load

## Continuous Integration

These test scripts can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run production tests
  run: ./test_prod_release.sh
  env:
    BASE_URL: http://localhost:8000
```

## Customization

To add custom tests:

1. Add a new phase section in the appropriate script
2. Use the existing helper functions (`run_test`, `check_http_status`, `test_api_endpoint`)
3. Update the test counters appropriately
4. Add cleanup logic if test data is created

## Security Considerations

- Test scripts create temporary users with API keys
- All test data is cleaned up after execution
- Avoid running against production databases without proper backups
- Use test environments that mirror production configuration

## Troubleshooting

### PowerShell Execution Policy
If you get execution policy errors in PowerShell:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Curl Not Found
Install curl or use the PowerShell version which uses `Invoke-WebRequest`.

### Django Commands Not Found
Ensure you're in the correct directory with manage.py and have the virtual environment activated.

## Support

For issues or questions about the test suite, please refer to the main project documentation or contact the development team.
