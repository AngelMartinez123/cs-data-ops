[CmdletBinding()]
param(
    [string] $UserName = '<SFTP_USERNAME>',
    [string] $CredentialFile = "$env:LOCALAPPDATA\FileTransfer-WinSCP\file_transfer-sftp-credential.clixml"
)

$ErrorActionPreference = 'Stop'
$directory = Split-Path -Parent $CredentialFile
New-Item -ItemType Directory -Path $directory -Force | Out-Null

$credential = Get-Credential -UserName $UserName -Message 'Enter the FileTransfer SFTP password. Windows will encrypt it for this account and PC.'
if (-not $credential) {
    throw 'Credential entry was cancelled.'
}
$credential | Export-Clixml -LiteralPath $CredentialFile -Force
Write-Host "Saved Windows-encrypted credential to: $CredentialFile"
Write-Host 'It can only be decrypted by this Windows account on this computer.'
