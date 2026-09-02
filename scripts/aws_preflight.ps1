# Checks AWS <AWS_PROFILE> profile and prints fix commands on failure.
param(
    [string]$Profile = "<AWS_PROFILE>"
)

$ErrorActionPreference = "Continue"
Write-Host "Data Operations AWS preflight (profile: $Profile)" -ForegroundColor Cyan

$envOk = $true
foreach ($var in @("ORACLE_USER", "ORACLE_PASSWORD")) {
    if (-not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($var, "User"))) {
        Write-Host "OK  Oracle env var present: $var"
    } else {
        Write-Host "FAIL Oracle env var missing: $var"
        Write-Host "     Fix: run oraclelogin in PowerShell, or set user-level ORACLE_* vars."
        $envOk = $false
    }
}

try {
    $identity = aws sts get-caller-identity --profile $Profile 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "OK  AWS STS identity:"
        Write-Host $identity
    } else {
        Write-Host "FAIL AWS STS check failed."
        Write-Host $identity
        Write-Host "Fix: aws-azure-login.cmd --profile $Profile --mode=gui --no-sandbox"
        exit 1
    }
} catch {
    Write-Host "FAIL aws CLI not available or command failed: $_"
    Write-Host "Fix: install AWS CLI and run aws-azure-login.cmd --profile $Profile --mode=gui --no-sandbox"
    exit 1
}

if (-not $envOk) {
    Write-Host ""
    Write-Host "Oracle env vars missing — AWS may be fine but Oracle scripts will fail." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Next: python .\scripts\data_ops_preflight.py"
Write-Host "Agent: call company-data MCP verify_data_access for MCP/VPN check."
