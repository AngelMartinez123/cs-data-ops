[CmdletBinding(SupportsShouldProcess)]
param(
    [string] $TaskName = 'Data Operations AWS Refresh'
)

$ErrorActionPreference = 'Stop'
$refreshScript = Join-Path $PSScriptRoot 'Refresh-AwsSession.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $refreshScript -PathType Leaf)) {
    throw "Refresh script not found: $refreshScript"
}

$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}"' -f $refreshScript
$action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Hours 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, 'Register hidden AWS refresh every two hours')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "Registered scheduled task: $TaskName"
}
