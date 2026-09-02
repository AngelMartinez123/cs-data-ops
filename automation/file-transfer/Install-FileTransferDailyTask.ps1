[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $TaskName = 'FileTransfer Daily Automation'
)

$ErrorActionPreference = 'Stop'
$coordinator = Join-Path $PSScriptRoot 'Invoke-FileTransferDaily.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

if (-not (Test-Path -LiteralPath $coordinator -PathType Leaf)) {
    throw "Coordinator not found: $coordinator"
}

$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f $coordinator
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
$trigger = for ($minutes = 7 * 60; $minutes -le (18 * 60 + 45); $minutes += 15) {
    New-ScheduledTaskTrigger -Daily -At (Get-Date).Date.AddMinutes($minutes)
}
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, 'Register per-user hidden task every 15 minutes')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered scheduled task: $TaskName"
}
