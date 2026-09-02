[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string] $InputFile,

    [ValidateRange(2000, 9999)]
    [int] $Year = (Get-Date).Year,

    [string] $ConfigPath,

    [switch] $ResumeExistingTarget
)

$ErrorActionPreference = 'Stop'
$session = $null
$runLog = $null

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $PSScriptRoot 'FileTransfer.WinSCP.config.psd1'
}

function Write-RunLog {
    param(
        [Parameter(Mandatory)] [string] $Message,
        [ValidateSet('INFO', 'ERROR')] [string] $Level = 'INFO'
    )

    $line = '{0:yyyy-MM-dd HH:mm:ss} [{1}] {2}' -f (Get-Date), $Level, $Message
    Write-Host $line
    if ($script:runLog) {
        Add-Content -LiteralPath $script:runLog -Value $line -Encoding utf8
    }
}

function Join-RemotePath {
    param([string] $Directory, [string] $Name)
    return ($Directory.TrimEnd('/') + '/' + $Name)
}

try {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "Configuration file not found: $ConfigPath"
    }
    $config = Import-PowerShellDataFile -LiteralPath $ConfigPath
    $config.LogDirectory = [Environment]::ExpandEnvironmentVariables($config.LogDirectory)
    if ($config.WinSCPAssemblyPath) {
        $config.WinSCPAssemblyPath = [Environment]::ExpandEnvironmentVariables($config.WinSCPAssemblyPath)
    }
    if ($config.SshPrivateKeyPath) {
        $config.SshPrivateKeyPath = [Environment]::ExpandEnvironmentVariables($config.SshPrivateKeyPath)
    }
    if ($config.CredentialFile) {
        $config.CredentialFile = [Environment]::ExpandEnvironmentVariables($config.CredentialFile)
    }
    if ($config.LocalDownloadDirectory) {
        $config.LocalDownloadDirectory = [Environment]::ExpandEnvironmentVariables($config.LocalDownloadDirectory)
    }

    foreach ($key in 'Protocol', 'HostName', 'UserName', 'RemoteInputDirectory',
             'RemoteOutputDirectory', 'PollIntervalSeconds', 'TimeoutMinutes',
             'StabilityWaitSeconds', 'DownloadOutput', 'LogDirectory') {
        if (-not $config.ContainsKey($key) -or $null -eq $config[$key] -or
            ($config[$key] -is [string] -and [string]::IsNullOrWhiteSpace($config[$key]))) {
            throw "Set '$key' in $ConfigPath before running the script."
        }
    }

    $resolvedInput = (Resolve-Path -LiteralPath $InputFile).Path
    if (-not (Test-Path -LiteralPath $resolvedInput -PathType Leaf)) {
        throw "Input file not found: $InputFile"
    }

    $fileName = [IO.Path]::GetFileName($resolvedInput)
    if ($fileName -notmatch '(?i)^file_transfer_input_(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)(\d{2})\.csv$') {
        throw "Input filename does not match file_transfer_input_<3-letter-month><2-digit-day>.csv: $fileName"
    }

    $monthNumbers = @{
        jan = 1; feb = 2; mar = 3; apr = 4; may = 5; jun = 6
        jul = 7; aug = 8; sep = 9; oct = 10; nov = 11; dec = 12
    }
    $monthText = $Matches[1].ToLowerInvariant()
    $day = [int]$Matches[2]
    try {
        $fileDate = [datetime]::new($Year, $monthNumbers[$monthText], $day)
    }
    catch {
        throw "The date encoded in '$fileName' is not valid for year $Year."
    }

    $targetName = 'file_transfer_matches_{0:yyyyMMdd}.csv' -f $fileDate
    $remoteInput = Join-RemotePath $config.RemoteInputDirectory $fileName
    $remoteExpectedOutput = Join-RemotePath $config.RemoteOutputDirectory $fileName
    $remoteTarget = Join-RemotePath $config.RemoteOutputDirectory $targetName

    New-Item -ItemType Directory -Path $config.LogDirectory -Force | Out-Null
    $runLog = Join-Path $config.LogDirectory ('file_transfer_{0:yyyyMMdd_HHmmss}.log' -f (Get-Date))
    Write-RunLog "Run started."
    Write-RunLog "Local input: $resolvedInput"
    Write-RunLog "Parsed date: $($fileDate.ToString('yyyy-MM-dd'))"
    Write-RunLog "Remote input: $remoteInput"
    Write-RunLog "Expected output: $remoteExpectedOutput"
    Write-RunLog "Final output: $remoteTarget"

    $assemblyCandidates = @(@(
        $config.WinSCPAssemblyPath
        (Join-Path $env:LOCALAPPDATA 'Programs\WinSCP\WinSCPnet.dll')
        (Join-Path $env:ProgramFiles 'WinSCP\WinSCPnet.dll')
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} 'WinSCP\WinSCPnet.dll' })
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) })

    if (-not $assemblyCandidates) {
        throw 'WinSCPnet.dll was not found. Install WinSCP or set WinSCPAssemblyPath in the config file.'
    }
    $assemblyPath = [string]$assemblyCandidates[0]
    Write-RunLog "Using WinSCP assembly: $assemblyPath"
    Add-Type -Path $assemblyPath

    try {
        $protocol = [WinSCP.Protocol]::$($config.Protocol)
    }
    catch {
        throw "Unsupported Protocol '$($config.Protocol)' in the config file."
    }

    $sessionOptions = [WinSCP.SessionOptions]::new()
    $sessionOptions.Protocol = $protocol
    $sessionOptions.HostName = $config.HostName
    $sessionOptions.UserName = $config.UserName
    if ($config.PortNumber) { $sessionOptions.PortNumber = [int]$config.PortNumber }

    if ($protocol -in @([WinSCP.Protocol]::Sftp, [WinSCP.Protocol]::Scp)) {
        if ([string]::IsNullOrWhiteSpace($config.SshHostKeyFingerprint)) {
            throw "Set 'SshHostKeyFingerprint' in $ConfigPath; host-key verification cannot be skipped."
        }
        $sessionOptions.SshHostKeyFingerprint = $config.SshHostKeyFingerprint
        if ($config.SshPrivateKeyPath) {
            $sessionOptions.SshPrivateKeyPath = $config.SshPrivateKeyPath
        }
    }

    if ($env:FileTransfer_SFTP_PASSWORD) {
        $sessionOptions.Password = $env:FileTransfer_SFTP_PASSWORD
    }
    elseif ($config.CredentialFile -and (Test-Path -LiteralPath $config.CredentialFile -PathType Leaf)) {
        $storedCredential = Import-Clixml -LiteralPath $config.CredentialFile
        if ($storedCredential -isnot [System.Management.Automation.PSCredential]) {
            throw "Credential file is invalid: $($config.CredentialFile)"
        }
        if ($storedCredential.UserName -ne $config.UserName) {
            throw "Credential username '$($storedCredential.UserName)' does not match configured username '$($config.UserName)'."
        }
        $sessionOptions.SecurePassword = $storedCredential.Password
        Write-RunLog "Loaded the Windows-encrypted credential for $($storedCredential.UserName)."
    }
    elseif (-not $config.SshPrivateKeyPath) {
        $sessionOptions.SecurePassword = Read-Host 'SFTP password' -AsSecureString
    }

    $session = [WinSCP.Session]::new()
    $session.Open($sessionOptions)
    Write-RunLog "Connected to $($config.HostName)."

    if ($session.FileExists($remoteTarget)) {
        if (-not $ResumeExistingTarget) {
            throw "Target file already exists; manual review required: $remoteTarget"
        }
        if (-not [bool]$config.DownloadOutput) {
            throw 'ResumeExistingTarget requires DownloadOutput to be enabled.'
        }
        New-Item -ItemType Directory -Path $config.LocalDownloadDirectory -Force | Out-Null
        $localTarget = Join-Path $config.LocalDownloadDirectory $targetName
        $remoteTargetInfo = $session.GetFileInfo($remoteTarget)
        if (Test-Path -LiteralPath $localTarget -PathType Leaf) {
            $localTargetSize = (Get-Item -LiteralPath $localTarget).Length
            if ($localTargetSize -ne $remoteTargetInfo.Length) {
                throw "Existing local result differs from the remote result; neither was overwritten: $localTarget"
            }
            Write-RunLog "Existing remote and local results match at $localTargetSize bytes; resuming."
        }
        else {
            $resumeTransferOptions = [WinSCP.TransferOptions]::new()
            $resumeTransferOptions.TransferMode = [WinSCP.TransferMode]::Binary
            $resumeDownload = $session.GetFiles($remoteTarget, $localTarget, $false, $resumeTransferOptions)
            $resumeDownload.Check()
            Write-RunLog "Downloaded existing remote result for resume: $localTarget"
        }
        Write-RunLog "Completed successfully from existing target."
        return
    }
    $remoteInputExists = $session.FileExists($remoteInput)
    if ($remoteInputExists -and -not $ResumeExistingTarget) {
        throw "Remote input already exists; it was not overwritten: $remoteInput"
    }

    $transferOptions = [WinSCP.TransferOptions]::new()
    $transferOptions.TransferMode = [WinSCP.TransferMode]::Binary
    if ($remoteInputExists) {
        Write-RunLog "Remote input already exists; resuming the wait without uploading again."
    }
    else {
        $transferResult = $session.PutFiles($resolvedInput, $remoteInput, $false, $transferOptions)
        $transferResult.Check()
        Write-RunLog "Upload complete."
    }

    $deadline = (Get-Date).AddMinutes([double]$config.TimeoutMinutes)
    $detectedAt = $null
    $stableSize = $null
    Write-RunLog "Waiting for backend output (timeout: $($config.TimeoutMinutes) minutes)."

    while ((Get-Date) -lt $deadline) {
        if ($session.FileExists($remoteExpectedOutput)) {
            if (-not $detectedAt) {
                $detectedAt = Get-Date
                Write-RunLog "Output detected at $($detectedAt.ToString('yyyy-MM-dd HH:mm:ss'))."
            }

            $first = $session.GetFileInfo($remoteExpectedOutput)
            Write-RunLog "Stability check: first size is $($first.Length) bytes."
            Start-Sleep -Seconds ([int]$config.StabilityWaitSeconds)

            if (-not $session.FileExists($remoteExpectedOutput)) {
                Write-RunLog "Output disappeared during stability check; continuing to wait."
                continue
            }

            $second = $session.GetFileInfo($remoteExpectedOutput)
            if ($first.Length -eq $second.Length -and $first.Length -gt 0) {
                $stableSize = $second.Length
                Write-RunLog "Output is stable at $stableSize bytes."
                break
            }
            Write-RunLog "Output size changed to $($second.Length) bytes; continuing to wait."
        }
        Start-Sleep -Seconds ([int]$config.PollIntervalSeconds)
    }

    if ($null -eq $stableSize) {
        throw "Expected output file was not found and stable within $($config.TimeoutMinutes) minutes: $remoteExpectedOutput"
    }

    # Repeat the collision check immediately before the rename to close the race window.
    if ($session.FileExists($remoteTarget)) {
        throw "Target file appeared while waiting; manual review required: $remoteTarget"
    }
    $session.MoveFile($remoteExpectedOutput, $remoteTarget)
    Write-RunLog "Rename complete: $remoteExpectedOutput -> $remoteTarget"

    if ([bool]$config.DownloadOutput) {
        if ([string]::IsNullOrWhiteSpace($config.LocalDownloadDirectory)) {
            throw "DownloadOutput is enabled, but LocalDownloadDirectory is not configured."
        }
        New-Item -ItemType Directory -Path $config.LocalDownloadDirectory -Force | Out-Null
        $localTarget = Join-Path $config.LocalDownloadDirectory $targetName
        if (Test-Path -LiteralPath $localTarget) {
            throw "Local download target already exists; it was not overwritten: $localTarget"
        }
        $downloadResult = $session.GetFiles($remoteTarget, $localTarget, $false, $transferOptions)
        $downloadResult.Check()
        Write-RunLog "Download complete: $localTarget"
    }
    else {
        Write-RunLog "Download disabled."
    }

    Write-RunLog "Completed successfully."
}
catch {
    Write-RunLog -Level ERROR -Message $_.Exception.Message
    exit 1
}
finally {
    if ($session) {
        $session.Dispose()
    }
    if ($runLog) {
        Write-RunLog "Run ended."
    }
}
