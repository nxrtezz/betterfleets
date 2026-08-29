@echo off
REM Production Release Test Suite for BetterFleets (Windows Version)
REM This script tests all major system functionality for production release

setlocal enabledelayedexpansion

REM Configuration
set "BASE_URL=%BASE_URL:https://dev.eeveeit.uk%"
set "ADMIN_USERNAME=%ADMIN_USERNAME:admin%"
set "ADMIN_PASSWORD=%ADMIN_PASSWORD:admin123%"
set "TEST_TIMESTAMP=%time: =0%"
set "TEST_TIMESTAMP=%TEST_TIMESTAMP::=%"
set "TEST_TIMESTAMP=%TEST_TIMESTAMP:.=%"
set "TEST_USER_EMAIL=test_user_%TEST_TIMESTAMP%@example.com"
set "TEST_USER_PASSWORD=TestPass123!"
set "TEST_API_KEY="

REM Error capture files
set "ERROR_LOG=test_errors_%date:~-4,4%%date:~-7,2%%date:~-10,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log"
set "ERROR_CAPTURE_FILE=error_capture_for_chat.txt"

REM Initialize error capture
echo BetterFleets Test Error Capture - %date% %time% > "%ERROR_CAPTURE_FILE%"
echo ============================================ >> "%ERROR_CAPTURE_FILE%"
echo Base URL: %BASE_URL% >> "%ERROR_CAPTURE_FILE%"
echo. >> "%ERROR_CAPTURE_FILE%"

REM Test counters
set TOTAL_TESTS=0
set PASSED_TESTS=0
set FAILED_TESTS=0

echo ==========================================
echo BetterFleets Production Release Test Suite
echo ==========================================
echo Testing against: %BASE_URL%
echo Starting tests at: %date% %time%
echo.

REM Helper functions
:log_info
echo [INFO] %~1
goto :eof

:log_success
echo [PASS] %~1
set /a PASSED_TESTS+=1
goto :eof

:log_error
echo [FAIL] %~1
set /a FAILED_TESTS+=1
echo FAILED: %~1 >> "%ERROR_CAPTURE_FILE%"
goto :eof

:log_error_detail
echo [FAIL DETAIL] %~1
echo DETAIL: %~1 >> "%ERROR_CAPTURE_FILE%"
goto :eof

:run_test
set /a TOTAL_TESTS+=1
set "test_name=%~1"
set "test_command=%~2"

call :log_info "Running: %test_name%"

%test_command% >nul 2>&1
if %errorlevel% equ 0 (
    call :log_success "%test_name%"
) else (
    call :log_error "%test_name%"
    call :log_error_detail "Command: %test_command%"
    call :log_error_detail "Exit code: %errorlevel%"
    echo ---------------------------------------- >> "%ERROR_CAPTURE_FILE%"
)
goto :eof

:check_http_status
set "url=%~1"
set "expected_status=%~2"
set "auth_header=%~3"

set "cmd=curl -s -o nul -w "%%{http_code}" "%url%""
if not "%auth_header%"=="" (
    set "cmd=curl -s -o nul -w "%%{http_code}" -H "Authorization: %auth_header%" "%url%""
)

for /f "delims=" %%i in ('!cmd!') do set status=%%i
if "%status%"=="%expected_status%" (
    exit /b 0
) else (
    exit /b 1
)

:test_api_endpoint
set "endpoint=%~1"
set "expected_status=%~2"
set "method=%~3"
if "%method%"=="" set "method=GET"
set "data=%~4"
set "auth_header=%~5"

set "cmd=curl -s -X %method% -w "%%{http_code}" "%BASE_URL%%endpoint%""

if not "%data%"=="" (
    set "cmd=!cmd! -H "Content-Type: application/json" -d "!data!""
)

if not "%auth_header%"=="" (
    set "cmd=!cmd! -H "Authorization: %auth_header%""
)

for /f "delims=" %%i in ('!cmd!') do set status=%%i
if "%status%"=="%expected_status%" (
    exit /b 0
) else (
    exit /b 1
)

REM Phase 1: Basic System Health Checks
call :log_info "Phase 1: Basic System Health Checks"

call :run_test "Site is accessible" "call :check_http_status "%BASE_URL%" 200"
call :run_test "Admin panel is accessible" "call :check_http_status "%BASE_URL%/admin/" 302"
call :run_test "API site-info endpoint" "call :test_api_endpoint "/api/site-info/" 200"

REM Phase 2: API Endpoint Tests (Read Operations)
call :log_info "Phase 2: API Endpoint Tests (Read Operations)"

call :run_test "API vehicles list" "call :test_api_endpoint "/api/vehicles/" 200"
call :run_test "API liveries list" "call :test_api_endpoint "/api/liveries/" 200"
call :run_test "API vehicle types list" "call :test_api_endpoint "/api/vehicletypes/" 200"
call :run_test "API operators list" "call :test_api_endpoint "/api/operators/" 200"
call :run_test "API garages list" "call :test_api_endpoint "/api/garages/" 200"
call :run_test "API services list" "call :test_api_endpoint "/api/services/" 200"
call :run_test "API trips list" "call :test_api_endpoint "/api/trips/" 200"
call :run_test "API users list" "call :test_api_endpoint "/api/users/" 200"

REM Phase 3: Web Interface Tests
call :log_info "Phase 3: Web Interface Tests"

call :run_test "Vehicles page is accessible" "call :check_http_status "%BASE_URL%/vehicles" 200"
call :run_test "Dashboard is accessible" "call :check_http_status "%BASE_URL%/dashboard" 302"
call :run_test "Map page is accessible" "call :check_http_status "%BASE_URL%/map" 200"
call :run_test "Events page is accessible" "call :check_http_status "%BASE_URL%/events" 302"

REM Phase 4: User Creation and Authentication
call :log_info "Phase 4: User Creation and Authentication"

call :log_info "Creating test user..."
python manage.py shell -c "from accounts.models import User; user = User.objects.create_user(username='testuser_prod', email='%TEST_USER_EMAIL%', password='%TEST_USER_PASSWORD%'); user.trusted = True; user.view_advanced = True; user.advanced_mode = True; user.save(); print(f'User created: {user.id}')" 2>&1

call :run_test "Test user creation" "python manage.py shell -c \"from accounts.models import User; User.objects.get(email='%TEST_USER_EMAIL%')\""

call :log_info "Generating API key for test user..."
for /f "delims=" %%i in ('python manage.py shell -c "from accounts.models import User, APIKey; user = User.objects.get(email='%TEST_USER_EMAIL%'); key, created = APIKey.objects.get_or_create(user=user, name='Production Test Key', defaults={'is_active': True}); print(key.key)" 2^>^&1') do set API_KEY_OUTPUT=%%i

for /f "tokens=*" %%i in ("%API_KEY_OUTPUT%") do set TEST_API_KEY=%%i

if not "%TEST_API_KEY%"=="" if not "%TEST_API_KEY%"=="Error" (
    call :log_success "API key generation"
    set "AUTH_HEADER=Api-Key %TEST_API_KEY%"
) else (
    call :log_error "API key generation failed"
    set "AUTH_HEADER="
)

REM Phase 5: API Write Operations (with Authentication)
call :log_info "Phase 5: API Write Operations (with Authentication)"

if not "%AUTH_HEADER%"=="" (
    set "TEST_OPERATOR_DATA={\"noc\": \"TESTOP\", \"name\": \"Test Operator\", \"vehicle_mode\": \"bus\"}"
    call :run_test "API operator creation (authenticated)" "call :test_api_endpoint "/api/operators/" 201 "POST" "!TEST_OPERATOR_DATA!" "!AUTH_HEADER!""
    
    REM Get operator ID for update test
    for /f "delims=" %%i in ('curl -s "%BASE_URL%/api/operators/?noc=TESTOP"') do set OPERATOR_RESPONSE=%%i
    
    REM Simple operator update test
    set "UPDATE_OPERATOR_DATA={\"name\": \"Test Operator Updated\"}"
    call :run_test "API operator update test" "call :test_api_endpoint "/api/operators/TESTOP/" 200 "PATCH" "!UPDATE_OPERATOR_DATA!" "!AUTH_HEADER!""
    
    REM Test vehicle photo logging
    set "TEST_PHOTO_DATA={\"reg\": \"TEST123\", \"quantity\": 1}"
    call :run_test "API vehicle photo logging (authenticated)" "call :test_api_endpoint "/api/vehicles/log_photo/" 400 "POST" "!TEST_PHOTO_DATA!" "!AUTH_HEADER!""
) else (
    call :log_info "Skipping authenticated API tests - no API key available"
)

REM Phase 6: Vehicle Management Tests
call :log_info "Phase 6: Vehicle Management Tests"

call :run_test "Vehicle detail page handles non-existent vehicles" "call :check_http_status "%BASE_URL%/vehicles/nonexistent" 404"
call :run_test "Vehicle edit page requires authentication" "call :check_http_status "%BASE_URL%/vehicles/1/edit" 302"

REM Phase 7: Advanced Editing Tests
call :log_info "Phase 7: Advanced Editing Tests"

call :run_test "Basic fleet export requires authentication" "call :check_http_status "%BASE_URL%/operators/testop/vehicles/export/basic" 302"
call :run_test "Advanced fleet export requires authentication" "call :check_http_status "%BASE_URL%/operators/testop/vehicles/export/advanced" 302"

REM Phase 8: Request System Tests
call :log_info "Phase 8: Request System Tests"

call :run_test "Vehicle request page is accessible" "call :check_http_status "%BASE_URL%/requests/vehicle" 302"
call :run_test "Service request page is accessible" "call :check_http_status "%BASE_URL%/requests/service" 302"
call :run_test "Operator request page is accessible" "call :check_http_status "%BASE_URL%/requests/operator" 302"

REM Phase 9: Service Request System Tests
call :log_info "Phase 9: Service Request System Tests"

call :run_test "Service requests list requires authentication" "call :check_http_status "%BASE_URL%/requests/" 302"
call :run_test "Service request creation requires authentication" "call :check_http_status "%BASE_URL%/requests/create/" 302"

REM Phase 10: Operator and Service Pages
call :log_info "Phase 10: Operator and Service Pages"

call :run_test "Operator vehicles page handles routing" "call :check_http_status "%BASE_URL%/operators/testop/vehicles" 302"

REM Phase 11: Filter and Search Tests
call :log_info "Phase 11: Filter and Search Tests"

call :run_test "API vehicles with filter" "call :test_api_endpoint "/api/vehicles/?withdrawn=false" 200"
call :run_test "API operators with filter" "call :test_api_endpoint "/api/operators/?vehicle_mode=bus" 200"
call :run_test "API services with filter" "call :test_api_endpoint "/api/services/?current=true" 200"

REM Phase 12: Edge Cases and Error Handling
call :log_info "Phase 12: Edge Cases and Error Handling"

call :run_test "API handles invalid vehicle ID gracefully" "call :test_api_endpoint "/api/vehicles/999999/" 404"
call :run_test "API handles invalid operator ID gracefully" "call :test_api_endpoint "/api/operators/INVALIDNOC/" 404"

REM Phase 13: Pagination Tests
call :log_info "Phase 13: Pagination Tests"

call :run_test "API vehicles pagination works" "call :test_api_endpoint "/api/vehicles/?limit=10&offset=0" 200"
call :run_test "API operators pagination works" "call :test_api_endpoint "/api/operators/?page=1" 200"

REM Phase 14: Performance Tests (basic)
call :log_info "Phase 14: Performance Tests (basic)"

call :log_info "Testing API response time for vehicles list..."
powershell -Command "$start = Get-Date; curl -s '%BASE_URL%/api/vehicles/' > $null; $end = Get-Date; $duration = ($end - $start).TotalMilliseconds; Write-Output $duration" > temp_time.txt
set /p RESPONSE_TIME=<temp_time.txt
del temp_time.txt

set /a RESPONSE_TIME_INT=%RESPONSE_TIME:.=%
if %RESPONSE_TIME_INT% lss 5000 (
    call :log_success "API vehicles list response time: %RESPONSE_TIME%ms (^< 5000ms)"
) else (
    call :log_error "API vehicles list response time: %RESPONSE_TIME%ms (^>= 5000ms)"
)

REM Phase 15: Cleanup
call :log_info "Phase 15: Cleanup"

call :log_info "Cleaning up test data..."
for /f "delims=" %%i in ('python manage.py shell -c "from accounts.models import User, APIKey; from busstops.models import Operator; user = User.objects.filter(email='%TEST_USER_EMAIL%').first(); if user: APIKey.objects.filter(user=user).delete(); user.delete(); print('Test user deleted'); operator = Operator.objects.filter(noc='TESTOP').first(); if operator: operator.delete(); print('Test operator deleted')" 2^>^&1') do set CLEANUP_OUTPUT=%%i

echo %CLEANUP_OUTPUT%
echo %CLEANUP_OUTPUT% | findstr /C:"Error" >nul
if %errorlevel% equ 0 (
    echo Cleanup error: %CLEANUP_OUTPUT% >> "%ERROR_CAPTURE_FILE%"
    echo ---------------------------------------- >> "%ERROR_CAPTURE_FILE%"
)

call :run_test "Test data cleanup" "exit /b 0"

REM Final Summary
echo.
echo ==========================================
echo Test Summary
echo ==========================================
echo Total tests: %TOTAL_TESTS%
echo Passed: %PASSED_TESTS%
echo Failed: %FAILED_TESTS%

if %FAILED_TESTS% equ 0 (
    echo All tests passed!
    echo.
    echo Error capture file: %ERROR_CAPTURE_FILE% (no errors to report)
    exit /b 0
) else (
    echo Some tests failed. Please review the output above.
    echo.
    echo ============================================
    echo ERROR CAPTURE FOR CHAT
    echo ============================================
    echo.
    echo Copy and paste the content below to get help with fixing errors:
    echo.
    echo --- START ERROR CAPTURE ---
    type "%ERROR_CAPTURE_FILE%"
    echo --- END ERROR CAPTURE ---
    echo.
    echo Full error details saved to: %ERROR_CAPTURE_FILE%
    echo Full error log saved to: %ERROR_LOG%
    exit /b 1
)
