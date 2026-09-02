[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$files = Get-ChildItem -LiteralPath $root -Recurse -File -Force |
    Where-Object {
        $_.FullName -notmatch '[\\/]\.git[\\/]' -and
        $_.FullName -notmatch '[\\/]__pycache__[\\/]'
    }

$blockedExtensions = @(
    '.csv', '.tsv', '.xlsx', '.xlsm', '.xlsb', '.pdf', '.zip', '.sqlite',
    '.db', '.log', '.clixml', '.pem', '.key', '.pfx', '.pyc'
)

$findings = [System.Collections.Generic.List[object]]::new()

foreach ($file in $files) {
    if ($file.Extension.ToLowerInvariant() -in $blockedExtensions) {
        $findings.Add([pscustomobject]@{
            Type = 'blocked-extension'
            File = $file.FullName.Substring($root.Length + 1)
            Line = 0
        })
    }
}

$patterns = [ordered]@{
    'private-key'       = '-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'
    'aws-access-key'    = '\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'
    'github-token'      = '\b(?:ghp|github_pat)_[A-Za-z0-9_]+'
    'password-literal'  = '(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*["''][^"'']{4,}'
    'personal-path'     = '(?i)C:\\Users\\(?!<USERNAME>)[^\\\s"'']+'
    'email-address'     = '(?i)\b(?!<USERNAME>@<COMPANY_DOMAIN>)[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'
    'live-safe-number'  = '\b(?:US|CA|GB|IE|NL|MX|FR)\d{6,12}\b'
    'live-company-id'   = '\b[A-Z]{2,4}_\d{4,}\b'
    'live-case-number'  = '\b(?!00000000)\d{8}\b'
    'internal-marker'   = '(?i)creditsafe|csus_core|csus_grouping|csusendh|lexisnexis|prodnet\.dom'
}

$textExtensions = @('.py', '.ps1', '.psd1', '.sql', '.md', '.mdc', '.json', '.yaml', '.yml', '.toml', '.txt')
foreach ($file in $files | Where-Object { $_.Extension.ToLowerInvariant() -in $textExtensions }) {
    foreach ($entry in $patterns.GetEnumerator()) {
        if ($entry.Key -eq 'internal-marker' -and $file.FullName -eq $PSCommandPath) {
            continue
        }
        $matches = Select-String -LiteralPath $file.FullName -Pattern $entry.Value -ErrorAction SilentlyContinue
        foreach ($match in $matches) {
            $findings.Add([pscustomobject]@{
                Type = $entry.Key
                File = $file.FullName.Substring($root.Length + 1)
                Line = $match.LineNumber
            })
        }
    }
}

if ($findings.Count -gt 0) {
    $findings | Sort-Object Type, File, Line | Format-Table -AutoSize
    Write-Error "Repository audit failed with $($findings.Count) finding(s). Values were intentionally not printed."
    exit 1
}

Write-Output "Repository audit passed for $($files.Count) files."
