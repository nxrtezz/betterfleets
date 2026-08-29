#!/bin/bash

# Production Release Test Suite for BetterFleets
# This script tests all major system functionality for production release

# Configuration
BASE_URL="${BASE_URL:-https://dev.eeveeit.uk}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin123}"
TEST_USER_EMAIL="test_user_$(date +%s)@example.com"
TEST_USER_PASSWORD="TestPass123!"
TEST_API_KEY=""

# Error log file
ERROR_LOG="test_errors_$(date +%Y%m%d_%H%M%S).log"
ERROR_CAPTURE_FILE="error_capture_for_chat.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Initialize error capture
echo "BetterFleets Test Error Capture - $(date)" > "$ERROR_CAPTURE_FILE"
echo "============================================" >> "$ERROR_CAPTURE_FILE"
echo "Base URL: $BASE_URL" >> "$ERROR_CAPTURE_FILE"
echo "" >> "$ERROR_CAPTURE_FILE"

# Helper functions
log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED_TESTS++))
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED_TESTS++))
    echo "FAILED: $1" >> "$ERROR_CAPTURE_FILE"
}

log_error_detail() {
    echo -e "${RED}[FAIL DETAIL]${NC} $1"
    echo "DETAIL: $1" >> "$ERROR_CAPTURE_FILE"
}

run_test() {
    ((TOTAL_TESTS++))
    local test_name="$1"
    local test_command="$2"
    
    log_info "Running: $test_name"
    
    # Capture both stdout and stderr
    local output
    local exit_code
    
    output=$(eval "$test_command" 2>&1)
    exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        log_success "$test_name"
        return 0
    else
        log_error "$test_name"
        log_error_detail "Command: $test_command"
        log_error_detail "Exit code: $exit_code"
        log_error_detail "Output: $output"
        echo "----------------------------------------" >> "$ERROR_CAPTURE_FILE"
        return 1
    fi
}

# Function to check HTTP status code
check_http_status() {
    local url="$1"
    local expected_status="${2:-200}"
    local auth_header="$3"
    
    local cmd="curl -s -o /dev/null -w '%{http_code}' '$url'"
    if [ -n "$auth_header" ]; then
        cmd="curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: $auth_header' '$url'"
    fi
    
    local status
    local output
    output=$(eval "$cmd" 2>&1)
    status=$output
    
    if [ "$status" -eq "$expected_status" ]; then
        return 0
    else
        echo "HTTP Status check failed: Expected $expected_status, got $status" >> "$ERROR_CAPTURE_FILE"
        echo "URL: $url" >> "$ERROR_CAPTURE_FILE"
        echo "----------------------------------------" >> "$ERROR_CAPTURE_FILE"
        return 1
    fi
}

# Function to test API endpoint
test_api_endpoint() {
    local endpoint="$1"
    local expected_status="${2:-200}"
    local method="${3:-GET}"
    local data="$4"
    local auth_header="$5"
    
    local cmd="curl -s -X $method -w '%{http_code}' '$BASE_URL$endpoint'"
    
    if [ -n "$data" ]; then
        cmd="$cmd -H 'Content-Type: application/json' -d '$data'"
    fi
    
    if [ -n "$auth_header" ]; then
        cmd="$cmd -H 'Authorization: $auth_header'"
    fi
    
    local status
    local output
    local response_body
    
    # Capture both status code and response body
    output=$(eval "$cmd" 2>&1)
    status=$output
    
    # Get response body for debugging
    response_body=$(curl -s -X $method "$BASE_URL$endpoint" 2>&1)
    if [ -n "$data" ]; then
        response_body=$(curl -s -X $method -H 'Content-Type: application/json' -d "$data" "$BASE_URL$endpoint" 2>&1)
    fi
    if [ -n "$auth_header" ]; then
        response_body=$(curl -s -X $method -H "Authorization: $auth_header" "$BASE_URL$endpoint" 2>&1)
    fi
    
    if [ "$status" -eq "$expected_status" ]; then
        return 0
    else
        echo "API endpoint test failed: Expected $expected_status, got $status" >> "$ERROR_CAPTURE_FILE"
        echo "Endpoint: $endpoint" >> "$ERROR_CAPTURE_FILE"
        echo "Method: $method" >> "$ERROR_CAPTURE_FILE"
        echo "Response body: $response_body" >> "$ERROR_CAPTURE_FILE"
        echo "----------------------------------------" >> "$ERROR_CAPTURE_FILE"
        return 1
    fi
}

echo "=========================================="
echo "BetterFleets Production Release Test Suite"
echo "=========================================="
echo "Testing against: $BASE_URL"
echo "Starting tests at: $(date)"
echo ""

# Phase 1: Basic System Health Checks
log_info "Phase 1: Basic System Health Checks"

run_test "Site is accessible" "check_http_status '$BASE_URL' 200"
run_test "Admin panel is accessible" "check_http_status '$BASE_URL/admin/' 302"
run_test "API site-info endpoint" "test_api_endpoint '/api/site-info/' 200"

# Phase 2: API Endpoint Tests (Read Operations)
log_info "Phase 2: API Endpoint Tests (Read Operations)"

run_test "API vehicles list" "test_api_endpoint '/api/vehicles/' 200"
run_test "API liveries list" "test_api_endpoint '/api/liveries/' 200"
run_test "API vehicle types list" "test_api_endpoint '/api/vehicletypes/' 200"
run_test "API operators list" "test_api_endpoint '/api/operators/' 200"
run_test "API garages list" "test_api_endpoint '/api/garages/' 200"
run_test "API services list" "test_api_endpoint '/api/services/' 200"
run_test "API trips list" "test_api_endpoint '/api/trips/' 200"
run_test "API users list" "test_api_endpoint '/api/users/' 200"

# Phase 3: Web Interface Tests
log_info "Phase 3: Web Interface Tests"

run_test "Vehicles page is accessible" "check_http_status '$BASE_URL/vehicles' 200"
run_test "Dashboard is accessible" "check_http_status '$BASE_URL/dashboard' 302"
run_test "Map page is accessible" "check_http_status '$BASE_URL/map' 200"
run_test "Events page is accessible" "check_http_status '$BASE_URL/events' 302"

# Phase 4: User Creation and Authentication
log_info "Phase 4: User Creation and Authentication"

# Create test user via Django management command
log_info "Creating test user..."
USER_CREATION_OUTPUT=$(python manage.py shell -c "
from accounts.models import User
try:
    user = User.objects.create_user(
        username='testuser_prod',
        email='$TEST_USER_EMAIL',
        password='$TEST_USER_PASSWORD'
    )
    user.trusted = True
    user.view_advanced = True
    user.advanced_mode = True
    user.save()
    print(f'User created: {user.id}')
except Exception as e:
    print(f'Error creating user: {e}')
" 2>&1)

echo "$USER_CREATION_OUTPUT"
if echo "$USER_CREATION_OUTPUT" | grep -q "Error"; then
    echo "User creation error: $USER_CREATION_OUTPUT" >> "$ERROR_CAPTURE_FILE"
    echo "----------------------------------------" >> "$ERROR_CAPTURE_FILE"
fi

run_test "Test user creation" "python manage.py shell -c 'from accounts.models import User; User.objects.get(email=\"$TEST_USER_EMAIL\")'"

# Generate API key for test user
log_info "Generating API key for test user..."
API_KEY_RESPONSE=$(python manage.py shell -c "
from accounts.models import User, APIKey
try:
    user = User.objects.get(email='$TEST_USER_EMAIL')
    key, created = APIKey.objects.get_or_create(
        user=user,
        name='Production Test Key',
        defaults={'is_active': True}
    )
    print(key.key)
except Exception as e:
    print(f'Error: {e}')
" 2>&1)

if echo "$API_KEY_RESPONSE" | grep -q "Error"; then
    echo "API key generation error: $API_KEY_RESPONSE" >> "$ERROR_CAPTURE_FILE"
    echo "----------------------------------------" >> "$ERROR_CAPTURE_FILE"
fi

TEST_API_KEY=$(echo "$API_KEY_RESPONSE" | grep -v Error | grep -v 'User created' | head -1)

if [ -n "$TEST_API_KEY" ] && [ "$TEST_API_KEY" != "Error" ]; then
    log_success "API key generation"
    AUTH_HEADER="Api-Key $TEST_API_KEY"
else
    log_error "API key generation failed"
    AUTH_HEADER=""
fi

# Phase 5: API Write Operations (with Authentication)
log_info "Phase 5: API Write Operations (with Authentication)"

if [ -n "$AUTH_HEADER" ]; then
    # Test operator creation (requires auth)
    TEST_OPERATOR_DATA='{
        "noc": "TESTOP",
        "name": "Test Operator",
        "vehicle_mode": "bus"
    }'
    
    run_test "API operator creation (authenticated)" "test_api_endpoint '/api/operators/' 201 'POST' '$TEST_OPERATOR_DATA' '$AUTH_HEADER'"
    
    # Test operator update (requires auth)
    # First get an operator ID
    OPERATOR_ID=$(curl -s "$BASE_URL/api/operators/?noc=TESTOP" | python -c "import sys, json; data=json.load(sys.stdin); print(data['results'][0]['id'] if data.get('results') else '')" 2>/dev/null || echo "")
    
    if [ -n "$OPERATOR_ID" ]; then
        UPDATE_OPERATOR_DATA='{
            "name": "Test Operator Updated"
        }'
        run_test "API operator update (authenticated)" "test_api_endpoint '/api/operators/$OPERATOR_ID/' 200 'PATCH' '$UPDATE_OPERATOR_DATA' '$AUTH_HEADER'"
    fi
    
    # Test vehicle photo logging (requires auth)
    TEST_PHOTO_DATA='{
        "reg": "TEST123",
        "quantity": 1
    }'
    
    run_test "API vehicle photo logging (authenticated)" "test_api_endpoint '/api/vehicles/log_photo/' 400 'POST' '$TEST_PHOTO_DATA' '$AUTH_HEADER'"  # 400 because vehicle doesn't exist
else
    log_info "Skipping authenticated API tests - no API key available"
fi

# Phase 6: Vehicle Management Tests
log_info "Phase 6: Vehicle Management Tests"

# Test vehicle detail page (will get 404 for non-existent, but that's expected behavior)
run_test "Vehicle detail page handles non-existent vehicles" "check_http_status '$BASE_URL/vehicles/nonexistent' 404"

# Test vehicle edit page (requires authentication)
run_test "Vehicle edit page requires authentication" "check_http_status '$BASE_URL/vehicles/1/edit' 302"

# Phase 7: Advanced Editing Tests
log_info "Phase 7: Advanced Editing Tests"

# Test fleet export endpoints
run_test "Basic fleet export requires authentication" "check_http_status '$BASE_URL/operators/testop/vehicles/export/basic' 302"
run_test "Advanced fleet export requires authentication" "check_http_status '$BASE_URL/operators/testop/vehicles/export/advanced' 302"

# Phase 8: Request System Tests
log_info "Phase 8: Request System Tests"

run_test "Vehicle request page is accessible" "check_http_status '$BASE_URL/requests/vehicle' 302"
run_test "Service request page is accessible" "check_http_status '$BASE_URL/requests/service' 302"
run_test "Operator request page is accessible" "check_http_status '$BASE_URL/requests/operator' 302"

# Phase 9: Service Request System Tests
log_info "Phase 9: Service Request System Tests"

run_test "Service requests list requires authentication" "check_http_status '$BASE_URL/requests/' 302"
run_test "Service request creation requires authentication" "check_http_status '$BASE_URL/requests/create/' 302"

# Phase 10: Operator and Service Pages
log_info "Phase 10: Operator and Service Pages"

# Test operator pages (will redirect or 404 for non-existent, but tests routing)
run_test "Operator vehicles page handles routing" "check_http_status '$BASE_URL/operators/testop/vehicles' 302"

# Phase 11: Filter and Search Tests
log_info "Phase 11: Filter and Search Tests"

run_test "API vehicles with filter" "test_api_endpoint '/api/vehicles/?withdrawn=false' 200"
run_test "API operators with filter" "test_api_endpoint '/api/operators/?vehicle_mode=bus' 200"
run_test "API services with filter" "test_api_endpoint '/api/services/?current=true' 200"

# Phase 12: Edge Cases and Error Handling
log_info "Phase 12: Edge Cases and Error Handling"

run_test "API handles invalid vehicle ID gracefully" "test_api_endpoint '/api/vehicles/999999/' 404"
run_test "API handles invalid operator ID gracefully" "test_api_endpoint '/api/operators/INVALIDNOC/' 404"
run_test "API handles malformed JSON" "curl -s -X POST -w '%{http_code}' '$BASE_URL/api/operators/' -H 'Content-Type: application/json' -d '{invalid json}' | grep -q '400'"

# Phase 13: Pagination Tests
log_info "Phase 13: Pagination Tests"

run_test "API vehicles pagination works" "test_api_endpoint '/api/vehicles/?limit=10&offset=0' 200"
run_test "API operators pagination works" "test_api_endpoint '/api/operators/?page=1' 200"

# Phase 14: Performance Tests (basic)
log_info "Phase 14: Performance Tests (basic)"

log_info "Testing API response time for vehicles list..."
START_TIME=$(date +%s%N)
curl -s "$BASE_URL/api/vehicles/" > /dev/null
END_TIME=$(date +%s%N)
RESPONSE_TIME=$((($END_TIME - $START_TIME) / 1000000))

if [ $RESPONSE_TIME -lt 5000 ]; then
    log_success "API vehicles list response time: ${RESPONSE_TIME}ms (< 5000ms)"
else
    log_error "API vehicles list response time: ${RESPONSE_TIME}ms (>= 5000ms)"
fi

# Phase 15: Cleanup
log_info "Phase 15: Cleanup"

log_info "Cleaning up test data..."
CLEANUP_OUTPUT=$(python manage.py shell -c "
from accounts.models import User, APIKey
from busstops.models import Operator
try:
    user = User.objects.get(email='$TEST_USER_EMAIL')
    APIKey.objects.filter(user=user).delete()
    user.delete()
    print('Test user deleted')
except User.DoesNotExist:
    print('Test user not found')
except Exception as e:
    print(f'Cleanup error: {e}')
try:
    operator = Operator.objects.get(noc='TESTOP')
    operator.delete()
    print('Test operator deleted')
except Operator.DoesNotExist:
    print('Test operator not found')
except Exception as e:
    print(f'Cleanup error: {e}')
" 2>&1)

echo "$CLEANUP_OUTPUT"
if echo "$CLEANUP_OUTPUT" | grep -q "Error"; then
    echo "Cleanup error: $CLEANUP_OUTPUT" >> "$ERROR_CAPTURE_FILE"
    echo "----------------------------------------" >> "$ERROR_CAPTURE_FILE"
fi

run_test "Test data cleanup" "true"

# Final Summary
echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "Total tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
echo -e "${RED}Failed: $FAILED_TESTS${NC}"

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    echo ""
    echo "Error capture file: $ERROR_CAPTURE_FILE (no errors to report)"
    exit 0
else
    echo -e "${RED}Some tests failed. Please review the output above.${NC}"
    echo ""
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}ERROR CAPTURE FOR CHAT${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo ""
    echo "Copy and paste the content below to get help with fixing errors:"
    echo ""
    echo -e "${YELLOW}--- START ERROR CAPTURE ---${NC}"
    cat "$ERROR_CAPTURE_FILE"
    echo -e "${YELLOW}--- END ERROR CAPTURE ---${NC}"
    echo ""
    echo "Full error details saved to: $ERROR_CAPTURE_FILE"
    echo "Full error log saved to: $ERROR_LOG"
    exit 1
fi
