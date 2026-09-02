[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $FileTransferTaskName = 'FileTransfer Daily Automation',
    [string] $AwsTaskName = 'Data Operations AWS Refresh'
)

$ErrorActionPreference = 'Stop'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$coordinator = Join-Path $PSScriptRoot 'Invoke-FileTransferDaily.ps1'
$refreshScript = Join-Path $PSScriptRoot 'Refresh-AwsSession.ps1'

foreach ($file in $powershell, $coordinator, $refreshScript) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required file not found: $file" }
}

$defaultUser = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$credential = Get-Credential -UserName $defaultUser `
    -Message 'Enter the Windows account that will own these unattended tasks.'
if (-not $credential) { throw 'Windows credential entry was cancelled.' }
$taskPassword = $credential.GetNetworkCredential().Password

$commonSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

$file_transferAction = New-ScheduledTaskAction -Execute $powershell -Argument (
    '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f $coordinator
)
$file_transferTriggers = for ($minutes = 7 * 60; $minutes -le (18 * 60 + 45); $minutes += 15) {
    New-ScheduledTaskTrigger -Daily -At (Get-Date).Date.AddMinutes($minutes)
}

$awsAction = New-ScheduledTaskAction -Execute $powershell -Argument (
    '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f $refreshScript
)
$awsTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Days 3650)
$awsSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

try {
    if ($PSCmdlet.ShouldProcess($FileTransferTaskName, 'Register unattended FileTransfer task')) {
        Register-ScheduledTask -TaskName $FileTransferTaskName -Action $file_transferAction -Trigger $file_transferTriggers `
            -Settings $commonSettings -User $credential.UserName -Password $taskPassword `
            -RunLevel Limited -Force | Out-Null
    }
    if ($PSCmdlet.ShouldProcess($AwsTaskName, 'Register unattended AWS refresh task')) {
        Register-ScheduledTask -TaskName $AwsTaskName -Action $awsAction -Trigger $awsTrigger `
            -Settings $awsSettings -User $credential.UserName -Password $taskPassword `
            -RunLevel Limited -Force | Out-Null
    }
}
finally {
    $taskPassword = $null
    $credential = $null
}

Write-Host 'Registered unattended tasks. They can run when the RDP user is logged off.'
