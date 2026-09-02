[CmdletBinding()]
param()

$checks = @()
function Add-Check([string] $Name, [bool] $Ok, [string] $Detail) {
    $script:checks += [pscustomobject]@{ Check = $Name; Status = $(if ($Ok) { 'OK' } else { 'FAIL' }); Detail = $Detail }
}

$winscpCandidates = @(@(
    (Join-Path $env:LOCALAPPDATA 'Programs\WinSCP\WinSCPnet.dll')
    (Join-Path $env:ProgramFiles 'WinSCP\WinSCPnet.dll')
    $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} 'WinSCP\WinSCPnet.dll' })
) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) })
Add-Check 'Windows PowerShell 5.1' ($PSVersionTable.PSVersion.Major -eq 5) $PSVersionTable.PSVersion.ToString()
Add-Check 'WinSCP .NET assembly' (@($winscpCandidates).Count -gt 0) $(if ($winscpCandidates) { $winscpCandidates[0] } else { 'Install WinSCP' })

$aws = Get-Command aws.exe -ErrorAction SilentlyContinue
if (-not $aws) { $aws = Get-Command aws -ErrorAction SilentlyContinue }
Add-Check 'AWS CLI' ($null -ne $aws) $(if ($aws) { $aws.Source } else { 'Install AWS CLI v2' })

$azureLogin = Get-Command aws-azure-login.cmd -ErrorAction SilentlyContinue
Add-Check 'aws-azure-login' ($null -ne $azureLogin) $(if ($azureLogin) { $azureLogin.Source } else { 'Install Node.js, then npm install -g aws-azure-login' })

$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
$botoOk = $false
$botoDetail = 'Install Python, then python -m pip install boto3'
if ($python) {
    & $python.Source -c "import boto3; print(boto3.__version__)" 2>$null | ForEach-Object { $botoDetail = "boto3 $_" }
    $botoOk = ($LASTEXITCODE -eq 0)
}
Add-Check 'Python + boto3' $botoOk $botoDetail

foreach ($file in 'Invoke-FileTransferDaily.ps1', 'Invoke-FileTransferWinSCP.ps1', 'Invoke-FileTransferAthenaPostprocess.py',
                  'FileTransfer.Daily.config.psd1', 'FileTransfer.WinSCP.config.psd1', 'Save-FileTransferCredential.ps1') {
    Add-Check $file (Test-Path -LiteralPath (Join-Path $PSScriptRoot $file) -PathType Leaf) (Join-Path $PSScriptRoot $file)
}

$checks | Format-Table -AutoSize -Wrap
if ($checks.Status -contains 'FAIL') { exit 1 }
exit 0
