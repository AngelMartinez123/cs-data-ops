param(
    [string]$Profile = $env:DATAOPS_AWS_PROFILE
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Profile)) {
    throw 'Set DATAOPS_AWS_PROFILE or pass -Profile before running.'
}
$logDirectory = Join-Path $env:LOCALAPPDATA 'FileTransfer-WinSCP\Logs'
$logPath = Join-Path $logDirectory 'aws_refresh.log'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-RefreshLog([string] $Message) {
    Add-Content -LiteralPath $logPath `
        -Value ('{0:yyyy-MM-dd HH:mm:ss} {1}' -f (Get-Date), $Message) `
        -Encoding utf8
}

try {
    $loginCommand = (Get-Command aws-azure-login.cmd -ErrorAction Stop).Source
    Write-RefreshLog 'AWS refresh started.'
    & $loginCommand --profile $Profile --mode=gui --no-sandbox --no-prompt
    if ($LASTEXITCODE -ne 0) {
        throw "aws-azure-login exited with code $LASTEXITCODE."
    }
    & aws sts get-caller-identity --profile $Profile --output text | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "AWS STS verification exited with code $LASTEXITCODE."
    }
    Write-RefreshLog 'AWS refresh and STS verification succeeded.'
}
catch {
    Write-RefreshLog ('ERROR: ' + $_.Exception.Message)
    exit 1
}
