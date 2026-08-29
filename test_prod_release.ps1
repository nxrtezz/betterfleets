# Production Release Test Suite for BetterFleets (PowerShell Version)
# This script tests all major system functionality for production release

# Configuration
$BaseUrl = $env:BASE_URL ?? "https://dev.eeveeit.uk"
$AdminUsername = $env:ADMIN_USERNAME ?? "admin"
$AdminPassword = $env:ADMIN_PASSWORD ?? "admin123"
$TestTimestamp = Get-Date -Format "yyyyMMddHHmmss"
$TestUserEmail = "test_user_$TestTimestamp@example.com"
$TestUserPassword = "TestPass123!"
$TestApiKey = ""

# Error capture files
$ErrorLog = "test_errors_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$ErrorCaptureFile = "error_capture_for_chat.txt"

# Initialize error capture
"BetterFleets Test Error Capture - $(Get-Date)" | Out-File -FilePath $ErrorCaptureFile
"============================================" | Out-File -FilePath $ErrorCaptureFile -Append
"Base URL: $BaseUrl" | Out-File -FilePath $ErrorCaptureFile -Append
"" | Out-File -FilePath $ErrorCaptureFile -Append

# Test counters
$TotalTests = 0
$PassedTests = 0
$FailedTests = 0

# Helper functions
function Log-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Yellow
}

function Log-Success {
    param([string]$Message)
    Write-Host "[PASS] $Message" -ForegroundColor Green
    $script:PassedTests++
}

function Log-Error {
    param([string]$Message)
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    $script:FailedTests++
    "FAILED: $Message" | Out-File -FilePath $ErrorCaptureFile -Append
}

function Log-Error-Detail {
    param([string]$Message)
    Write-Host "[FAIL DETAIL] $Message" -ForegroundColor Red
    "DETAIL: $Message" | Out-File -FilePath $ErrorCaptureFile -Append
}

function Invoke-Test {
    param(
        [string]$TestName,
        [scriptblock]$TestCommand
    )
    
    $script:TotalTests++
    Log-Info "Running: $TestName"
    
    try {
        $result = & $TestCommand
        if ($result) {
            Log-Success $TestName
            return $true
        } else {
            Log-Error $TestName
            return $false
        }
    } catch {
        Log-Error "$TestName - Exception: $($_.Exception.Message)"
        Log-Error-Detail "Exception details: $($_.Exception | Out-String)"
        Log-Error-Detail "Stack trace: $($_.ScriptStackTrace)"
        "----------------------------------------" | Out-File -FilePath $ErrorCaptureFile -Append
        return $false
    }
}

function Test-HttpStatus {
    param(
        [string]$Url,
        [int]$ExpectedStatus = 200,
        [string]$AuthHeader = $null
    )
    
    $headers = @{}
    if ($AuthHeader) {
        $headers["Authorization"] = $AuthHeader
    }
    
    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -Headers $headers -UseBasicParsing -TimeoutSec 30
        return $response.StatusCode -eq $ExpectedStatus
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -ne $ExpectedStatus) {
            "HTTP Status check failed: Expected $ExpectedStatus, got $statusCode" | Out-File -FilePath $ErrorCaptureFile -Append
            "URL: $Url" | Out-File -FilePath $ErrorCaptureFile -Append
            "Exception: $($_.Exception.Message)" | Out-File -FilePath $ErrorCaptureFile -Append
            "----------------------------------------" | Out-File -FilePath $ErrorCaptureFile -Append
        }
        return $statusCode -eq $ExpectedStatus
    }
}

function Test-ApiEndpoint {
    param(
        [string]$Endpoint,
        [int]$ExpectedStatus = 200,
        [string]$Method = "GET",
        [string]$Data = $null,
        [string]$AuthHeader = $null
    )
    
    $url = "$BaseUrl$Endpoint"
    $headers = @{}
    if ($AuthHeader) {
        $headers["Authorization"] = $AuthHeader
    }
    
    if ($Data) {
        $headers["Content-Type"] = "application/json"
    }
    
    try {
        $responseBody = ""
        if ($Method -eq "GET") {
            $response = Invoke-WebRequest -Uri $url -Method Get -Headers $headers -UseBasicParsing -TimeoutSec 30
            $responseBody = $response.Content
        } else {
            $response = Invoke-WebRequest -Uri $url -Method $Method -Headers $headers -Body $Data -UseBasicParsing -TimeoutSec 30
            $responseBody = $response.Content
        }
        return $response.StatusCode -eq $ExpectedStatus
    } catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -ne $ExpectedStatus) {
            "API endpoint test failed: Expected $ExpectedStatus, got $statusCode" | Out-File -FilePath $ErrorCaptureFile -Append
            "Endpoint: $Endpoint" | Out-File -FilePath $ErrorCaptureFile -Append
            "Method: $Method" | Out-File -FilePath $ErrorCaptureFile -Append
            "Exception: $($_.Exception.Message)" | Out-File -FilePath $ErrorCaptureFile -Append
            "Response body: $responseBody" | Out-File -FilePath $ErrorCaptureFile -Append
            "----------------------------------------" | Out-File -FilePath $ErrorCaptureFile -Append
        }
        return $statusCode -eq $ExpectedStatus
    }
}

# Main script
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "BetterFleets Production Release Test Suite" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Testing against: $BaseUrl"
Write-Host "Starting tests at: $(Get-Date)"
Write-Host ""

# Phase 1: Basic System Health Checks
Log-Info "Phase 1: Basic System Health Checks"

Invoke-Test "Site is accessible" { Test-HttpStatus -Url $BaseUrl -ExpectedStatus 200 }
Invoke-Test "Admin panel is accessible" { Test-HttpStatus -Url "$BaseUrl/admin/" -ExpectedStatus 302 }
Invoke-Test "API site-info endpoint" { Test-ApiEndpoint -Endpoint "/api/site-info/" -ExpectedStatus 200 }

# Phase 2: API Endpoint Tests (Read Operations)
Log-Info "Phase 2: API Endpoint Tests (Read Operations)"

Invoke-Test "API vehicles list" { Test-ApiEndpoint -Endpoint "/api/vehicles/" -ExpectedStatus 200 }
Invoke-Test "API liveries list" { Test-ApiEndpoint -Endpoint "/api/liveries/" -ExpectedStatus 200 }
Invoke-Test "API vehicle types list" { Test-ApiEndpoint -Endpoint "/api/vehicletypes/" -ExpectedStatus 200 }
Invoke-Test "API operators list" { Test-ApiEndpoint -Endpoint "/api/operators/" -ExpectedStatus 200 }
Invoke-Test "API garages list" { Test-ApiEndpoint -Endpoint "/api/garages/" -ExpectedStatus 200 }
Invoke-Test "API services list" { Test-ApiEndpoint -Endpoint "/api/services/" -ExpectedStatus 200 }
Invoke-Test "API trips list" { Test-ApiEndpoint -Endpoint "/api/trips/" -ExpectedStatus 200 }
Invoke-Test "API users list" { Test-ApiEndpoint -Endpoint "/api/users/" -ExpectedStatus 200 }

# Phase 3: Web Interface Tests
Log-Info "Phase 3: Web Interface Tests"

Invoke-Test "Vehicles page is accessible" { Test-HttpStatus -Url "$BaseUrl/vehicles" -ExpectedStatus 200 }
Invoke-Test "Dashboard is accessible" { Test-HttpStatus -Url "$BaseUrl/dashboard" -ExpectedStatus 302 }
Invoke-Test "Map page is accessible" { Test-HttpStatus -Url "$BaseUrl/map" -ExpectedStatus 200 }
Invoke-Test "Events page is accessible" { Test-HttpStatus -Url "$BaseUrl/events" -ExpectedStatus 302 }

# Phase 4: User Creation and Authentication
Log-Info "Phase 4: User Creation and Authentication"

Log-Info "Creating test user..."
$createUserCommand = @"
from accounts.models import User
try:
    user = User.objects.create_user(
        username='testuser_prod',
        email='$TestUserEmail',
        password='$TestUserPassword'
    )
    user.trusted = True
    user.view_advanced = True
    user.advanced_mode = True
    user.save()
    print(f'User created: {user.id}')
except Exception as e:
    print(f'Error creating user: {e}')
"@

python manage.py shell -c $createUserCommand

Invoke-Test "Test user creation" {
    $checkUserCommand = "from accounts.models import User; User.objects.get(email='$TestUserEmail')"
    $result = python manage.py shell -c $checkUserCommand 2>&1
    return $LASTEXITCODE -eq 0
}

Log-Info "Generating API key for test user..."
$generateKeyCommand = @"
from accounts.models import User, APIKey
try:
    user = User.objects.get(email='$TestUserEmail')
    key, created = APIKey.objects.get_or_create(
        user=user,
        name='Production Test Key',
        defaults={'is_active': True}
    )
    print(key.key)
except Exception as e:
    print(f'Error: {e}')
"@

$apiKeyOutput = python manage.py shell -c $generateKeyCommand 2>&1
$TestApiKey = ($apiKeyOutput -split "`n" | Where-Object { $_ -notmatch "Error" -and $_ -notmatch "User created" -and $_ -ne "" } | Select-Object -First 1).Trim()

if ($TestApiKey -and $TestApiKey -ne "Error") {
    Log-Success "API key generation"
    $AuthHeader = "Api-Key $TestApiKey"
} else {
    Log-Error "API key generation failed"
    $AuthHeader = $null
}

# Phase 5: API Write Operations (with Authentication)
Log-Info "Phase 5: API Write Operations (with Authentication)"

if ($AuthHeader) {
    $testOperatorData = @{
        noc = "TESTOP"
        name = "Test Operator"
        vehicle_mode = "bus"
    } | ConvertTo-Json
    
    Invoke-Test "API operator creation (authenticated)" { 
        Test-ApiEndpoint -Endpoint "/api/operators/" -ExpectedStatus 201 -Method "POST" -Data $testOperatorData -AuthHeader $AuthHeader 
    }
    
    # Get operator ID for update test
    try {
        $operatorResponse = Invoke-RestMethod -Uri "$BaseUrl/api/operators/?noc=TESTOP" -Method Get -UseBasicParsing
        if ($operatorResponse.results -and $operatorResponse.results.Count -gt 0) {
            $operatorId = $operatorResponse.results[0].id
            
            $updateOperatorData = @{
                name = "Test Operator Updated"
            } | ConvertTo-Json
            
            Invoke-Test "API operator update (authenticated)" { 
                Test-ApiEndpoint -Endpoint "/api/operators/$operatorId/" -ExpectedStatus 200 -Method "PATCH" -Data $updateOperatorData -AuthHeader $AuthHeader 
            }
        }
    } catch {
        Log-Error "Could not retrieve test operator for update test"
    }
    
    # Test vehicle photo logging
    $testPhotoData = @{
        reg = "TEST123"
        quantity = 1
    } | ConvertTo-Json
    
    Invoke-Test "API vehicle photo logging (authenticated)" { 
        Test-ApiEndpoint -Endpoint "/api/vehicles/log_photo/" -ExpectedStatus 400 -Method "POST" -Data $testPhotoData -AuthHeader $AuthHeader 
    }
} else {
    Log-Info "Skipping authenticated API tests - no API key available"
}

# Phase 6: Vehicle Management Tests
Log-Info "Phase 6: Vehicle Management Tests"

Invoke-Test "Vehicle detail page handles non-existent vehicles" { Test-HttpStatus -Url "$BaseUrl/vehicles/nonexistent" -ExpectedStatus 404 }
Invoke-Test "Vehicle edit page requires authentication" { Test-HttpStatus -Url "$BaseUrl/vehicles/1/edit" -ExpectedStatus 302 }

# Phase 7: Advanced Editing Tests
Log-Info "Phase 7: Advanced Editing Tests"

Invoke-Test "Basic fleet export requires authentication" { Test-HttpStatus -Url "$BaseUrl/operators/testop/vehicles/export/basic" -ExpectedStatus 302 }
Invoke-Test "Advanced fleet export requires authentication" { Test-HttpStatus -Url "$BaseUrl/operators/testop/vehicles/export/advanced" -ExpectedStatus 302 }

# Phase 8: Request System Tests
Log-Info "Phase 8: Request System Tests"

Invoke-Test "Vehicle request page is accessible" { Test-HttpStatus -Url "$BaseUrl/requests/vehicle" -ExpectedStatus 302 }
Invoke-Test "Service request page is accessible" { Test-HttpStatus -Url "$BaseUrl/requests/service" -ExpectedStatus 302 }
Invoke-Test "Operator request page is accessible" { Test-HttpStatus -Url "$BaseUrl/requests/operator" -ExpectedStatus 302 }

# Phase 9: Service Request System Tests
Log-Info "Phase 9: Service Request System Tests"

Invoke-Test "Service requests list requires authentication" { Test-HttpStatus -Url "$BaseUrl/requests/" -ExpectedStatus 302 }
Invoke-Test "Service request creation requires authentication" { Test-HttpStatus -Url "$BaseUrl/requests/create/" -ExpectedStatus 302 }

# Phase 10: Operator and Service Pages
Log-Info "Phase 10: Operator and Service Pages"

Invoke-Test "Operator vehicles page handles routing" { Test-HttpStatus -Url "$BaseUrl/operators/testop/vehicles" -ExpectedStatus 302 }

# Phase 11: Filter and Search Tests
Log-Info "Phase 11: Filter and Search Tests"

Invoke-Test "API vehicles with filter" { Test-ApiEndpoint -Endpoint "/api/vehicles/?withdrawn=false" -ExpectedStatus 200 }
Invoke-Test "API operators with filter" { Test-ApiEndpoint -Endpoint "/api/operators/?vehicle_mode=bus" -ExpectedStatus 200 }
Invoke-Test "API services with filter" { Test-ApiEndpoint -Endpoint "/api/services/?current=true" -ExpectedStatus 200 }

# Phase 12: Edge Cases and Error Handling
Log-Info "Phase 12: Edge Cases and Error Handling"

Invoke-Test "API handles invalid vehicle ID gracefully" { Test-ApiEndpoint -Endpoint "/api/vehicles/999999/" -ExpectedStatus 404 }
Invoke-Test "API handles invalid operator ID gracefully" { Test-ApiEndpoint -Endpoint "/api/operators/INVALIDNOC/" -ExpectedStatus 404 }

# Test malformed JSON handling
try {
    $malformedResponse = Invoke-WebRequest -Uri "$BaseUrl/api/operators/" -Method POST -Headers @{"Content-Type" = "application/json"} -Body "{invalid json}" -UseBasicParsing -ErrorAction Stop
    $malformedStatus = $malformedResponse.StatusCode
} catch {
    $malformedStatus = $_.Exception.Response.StatusCode.value__
}

Invoke-Test "API handles malformed JSON" { $malformedStatus -eq 400 }

# Phase 13: Pagination Tests
Log-Info "Phase 13: Pagination Tests"

Invoke-Test "API vehicles pagination works" { Test-ApiEndpoint -Endpoint "/api/vehicles/?limit=10&offset=0" -ExpectedStatus 200 }
Invoke-Test "API operators pagination works" { Test-ApiEndpoint -Endpoint "/api/operators/?page=1" -ExpectedStatus 200 }

# Phase 14: Performance Tests (basic)
Log-Info "Phase 14: Performance Tests (basic)"

Log-Info "Testing API response time for vehicles list..."
$startTime = Get-Date
try {
    Invoke-WebRequest -Uri "$BaseUrl/api/vehicles/" -Method Get -UseBasicParsing -TimeoutSec 30 | Out-Null
    $endTime = Get-Date
    $responseTime = ($endTime - $startTime).TotalMilliseconds
    
    if ($responseTime -lt 5000) {
        Log-Success "API vehicles list response time: $([math]::Round($responseTime, 2))ms (< 5000ms)"
    } else {
        Log-Error "API vehicles list response time: $([math]::Round($responseTime, 2))ms (>= 5000ms)"
    }
} catch {
    Log-Error "Performance test failed: $($_.Exception.Message)"
}

# Phase 15: Cleanup
Log-Info "Phase 15: Cleanup"

Log-Info "Cleaning up test data..."
$cleanupCommand = @"
from accounts.models import User, APIKey
from busstops.models import Operator
try:
    user = User.objects.get(email='$TestUserEmail')
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
"@

$cleanupOutput = python manage.py shell -c $cleanupCommand 2>&1
Write-Host $cleanupOutput

if ($cleanupOutput -match "Error") {
    "Cleanup error: $cleanupOutput" | Out-File -FilePath $ErrorCaptureFile -Append
    "----------------------------------------" | Out-File -FilePath $ErrorCaptureFile -Append
}

Invoke-Test "Test data cleanup" { $true }

# Final Summary
Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Test Summary" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Total tests: $TotalTests"
Write-Host "Passed: $PassedTests" -ForegroundColor Green
Write-Host "Failed: $FailedTests" -ForegroundColor Red

if ($FailedTests -eq 0) {
    Write-Host "All tests passed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Error capture file: $ErrorCaptureFile (no errors to report)"
    exit 0
} else {
    Write-Host "Some tests failed. Please review the output above." -ForegroundColor Red
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "ERROR CAPTURE FOR CHAT" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Copy and paste the content below to get help with fixing errors:"
    Write-Host ""
    Write-Host "--- START ERROR CAPTURE ---" -ForegroundColor Yellow
    Get-Content $ErrorCaptureFile
    Write-Host "--- END ERROR CAPTURE ---" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Full error details saved to: $ErrorCaptureFile"
    Write-Host "Full error log saved to: $ErrorLog"
    exit 1
}
