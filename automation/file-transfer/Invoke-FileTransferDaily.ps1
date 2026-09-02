[CmdletBinding()]
param(
    [datetime] $ProcessDate = (Get-Date).Date,
    [string] $ConfigPath,
    [switch] $CheckOnly
)

$ErrorActionPreference = 'Stop'
$dailyLog = $null

if (-not $PSBoundParameters.ContainsKey('ProcessDate') -and
    (Get-Date).DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)) {
    exit 0
}

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot 'FileTransfer.Daily.config.psd1'
}

function Write-DailyLog {
    param(
        [Parameter(Mandatory)] [string] $Message,
        [ValidateSet('INFO', 'ERROR')] [string] $Level = 'INFO'
    )
    $line = '{0:yyyy-MM-dd HH:mm:ss} [{1}] {2}' -f (Get-Date), $Level, $Message
    Write-Host $line
    if ($script:dailyLog) {
        Add-Content -LiteralPath $script:dailyLog -Value $line -Encoding utf8
    }
}

try {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "Daily configuration file not found: $ConfigPath"
    }
    $config = Import-PowerShellDataFile -LiteralPath $ConfigPath
    foreach ($key in 'AwsProfile', 'AwsRegion', 'S3Bucket', 'S3Prefix',
             'BankruptcyCandidatesPrefix', 'BkFilePrefix', 'BkOutputNameTemplate',
             'AthenaCatalog', 'AthenaDatabase', 'AthenaWorkGroup',
             'LocalInputFolder', 'StateDirectory', 'LogDirectory') {
        if (-not $config.ContainsKey($key) -or [string]::IsNullOrWhiteSpace([string]$config[$key])) {
            throw "Set '$key' in $ConfigPath."
        }
    }

    foreach ($key in 'LocalInputFolder', 'StateDirectory', 'LogDirectory') {
        $config[$key] = [Environment]::ExpandEnvironmentVariables($config[$key])
    }
    New-Item -ItemType Directory -Path $config.LogDirectory -Force | Out-Null
    $dailyLog = Join-Path $config.LogDirectory ('file_transfer_daily_{0:yyyyMMdd_HHmmss}.log' -f (Get-Date))

    $dateId = $ProcessDate.ToString('yyyyMMdd')
    $sourceName = 'file_transfer_input_{0}.csv' -f $ProcessDate.ToString('MMMdd').ToLowerInvariant()
    $s3Key = '{0}/{1}' -f $config.S3Prefix.Trim('/'), $sourceName
    $s3Uri = 's3://{0}/{1}' -f $config.S3Bucket, $s3Key
    $localInput = Join-Path $config.LocalInputFolder $sourceName
    $markerPath = Join-Path $config.StateDirectory ($dateId + '.completed.json')

    Write-DailyLog "Daily coordinator started for $dateId."
    Write-DailyLog "Expected source: $s3Uri"

    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        Write-DailyLog "Already completed for $dateId; no action taken."
        exit 0
    }

    $aws = Get-Command aws.exe -ErrorAction SilentlyContinue
    if (-not $aws) { $aws = Get-Command aws -ErrorAction SilentlyContinue }
    if (-not $aws) { throw 'AWS CLI was not found in PATH.' }

    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $headText = & $aws.Source s3api head-object `
            --bucket $config.S3Bucket `
            --key $s3Key `
            --profile $config.AwsProfile `
            --region $config.AwsRegion `
            --output json 2>&1
        $headExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($headExitCode -ne 0) {
        $detail = ($headText | Out-String).Trim()
        if ($detail -match '404|Not Found|HeadObject operation') {
            Write-DailyLog "Today's S3 input is not available yet; this is a normal no-op."
            exit 0
        }
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "AWS CLI exit code $headExitCode" }
        throw "Unable to inspect S3 input. $detail"
    }
    $head = ($headText | Out-String) | ConvertFrom-Json
    $remoteSize = [long]$head.ContentLength
    if ($remoteSize -le 0) { throw "S3 input is empty: $s3Uri" }
    Write-DailyLog "S3 input is ready at $remoteSize bytes."

    if ($CheckOnly) {
        Write-DailyLog "CHECK ONLY: would download to $localInput and run the WinSCP workflow."
        exit 0
    }

    New-Item -ItemType Directory -Path $config.LocalInputFolder -Force | Out-Null
    if (Test-Path -LiteralPath $localInput -PathType Leaf) {
        $localSize = (Get-Item -LiteralPath $localInput).Length
        if ($localSize -ne $remoteSize) {
            throw "Local input already exists with a different size; it was not overwritten: $localInput"
        }
        Write-DailyLog "Matching local input already exists; reusing it."
    }
    else {
        & $aws.Source s3 cp $s3Uri $localInput `
            --profile $config.AwsProfile `
            --region $config.AwsRegion `
            --only-show-errors
        if ($LASTEXITCODE -ne 0) { throw "S3 download failed: $s3Uri" }
        $downloadedSize = (Get-Item -LiteralPath $localInput).Length
        if ($downloadedSize -ne $remoteSize) {
            throw "Downloaded size $downloadedSize does not match S3 size $remoteSize."
        }
        Write-DailyLog "Downloaded and size-verified: $localInput"
    }

    $workflowScript = Join-Path $PSScriptRoot 'Invoke-FileTransferWinSCP.ps1'
    $windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf)) {
        throw "Windows PowerShell 5.1 was not found: $windowsPowerShell"
    }

    $file_transferResultName = 'file_transfer_matches_{0}.csv' -f $dateId
    $file_transferResultPath = Join-Path $config.LocalInputFolder $file_transferResultName
    if (Test-Path -LiteralPath $file_transferResultPath -PathType Leaf) {
        Write-DailyLog "Existing local FileTransfer result found; resuming at post-processing: $file_transferResultPath"
    }
    else {
        Write-DailyLog "Starting WinSCP workflow."
        & $windowsPowerShell -NoProfile -NonInteractive -File $workflowScript `
            -InputFile $localInput -Year $ProcessDate.Year -ResumeExistingTarget
        if ($LASTEXITCODE -ne 0) { throw "WinSCP workflow failed with exit code $LASTEXITCODE." }
        if (-not (Test-Path -LiteralPath $file_transferResultPath -PathType Leaf)) {
            throw "Downloaded FileTransfer result was not found: $file_transferResultPath"
        }
    }
    $bkOutputName = $config.BkOutputNameTemplate -f $dateId
    $bkOutputPath = Join-Path $config.LocalInputFolder $bkOutputName
    $postprocessScript = Join-Path $PSScriptRoot 'Invoke-FileTransferAthenaPostprocess.py'
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $python) { throw 'Python was not found in PATH.' }

    Write-DailyLog "Starting FileTransfer S3/Athena post-processing."
    & $python.Source $postprocessScript `
        --date $dateId `
        --file-transfer-file $file_transferResultPath `
        --local-output $bkOutputPath `
        --profile $config.AwsProfile `
        --region $config.AwsRegion `
        --bucket $config.S3Bucket `
        --candidates-prefix $config.BankruptcyCandidatesPrefix `
        --bk-prefix $config.BkFilePrefix `
        --bk-output-name $bkOutputName `
        --catalog $config.AthenaCatalog `
        --database $config.AthenaDatabase `
        --workgroup $config.AthenaWorkGroup `
        --resume-existing
    if ($LASTEXITCODE -ne 0) { throw "FileTransfer S3/Athena post-processing failed with exit code $LASTEXITCODE." }
    Write-DailyLog "FileTransfer S3/Athena post-processing completed: $bkOutputPath"

    New-Item -ItemType Directory -Path $config.StateDirectory -Force | Out-Null
    $marker = [ordered]@{
        completed_at = (Get-Date).ToString('o')
        process_date = $dateId
        s3_uri = $s3Uri
        s3_size = $remoteSize
        local_input = $localInput
        file_transfer_output = $file_transferResultPath
        bk_output = $bkOutputPath
        bk_s3_uri = 's3://{0}/{1}/{2}' -f $config.S3Bucket, $config.BkFilePrefix.Trim('/'), $bkOutputName
    }
    $marker | ConvertTo-Json | Set-Content -LiteralPath $markerPath -Encoding utf8
    Write-DailyLog "Completed successfully; marker written to $markerPath"
}
catch {
    $errorMessage = $_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($errorMessage)) { $errorMessage = ($_ | Out-String).Trim() }
    if ([string]::IsNullOrWhiteSpace($errorMessage)) { $errorMessage = 'Unknown daily coordinator failure.' }
    Write-DailyLog -Level ERROR -Message $errorMessage
    exit 1
}
finally {
    if ($dailyLog) { Write-DailyLog 'Daily coordinator ended.' }
}
