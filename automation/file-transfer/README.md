# FileTransfer WinSCP automation

This script uploads one `file-transfer_input_<mon><day>.csv`, waits for the backend output,
checks that its size has stopped changing, and remotely renames it to
`file-transfer_matches_YYYYMMDD.csv`. Existing remote input, remote target, and local
download files are never overwritten.

## Configure

WinSCP is already installed on this PC at
`%LOCALAPPDATA%\Programs\WinSCP`, and the script detects its .NET assembly.

1. Edit `FileTransfer.WinSCP.config.psd1` and set the host, username, verified SSH host-key
   fingerprint, and real remote folders.
2. To save the password once using Windows user/machine encryption, run:

   ```powershell
   powershell.exe -NoProfile -File .\Save-FileTransferCredential.ps1
   ```

   Future runs load that encrypted credential automatically. It can only be
   decrypted by the same Windows account on the same computer. The script falls
   back to a secure prompt if the credential file does not exist.

   You may alternatively set a password only for the current PowerShell process:

   ```powershell
   $securePassword = Read-Host 'SFTP password' -AsSecureString
   $credential = New-Object System.Management.Automation.PSCredential('unused', $securePassword)
   $env:FileTransfer_SFTP_PASSWORD = $credential.GetNetworkCredential().Password
   ```

   The prompt/environment value is not written to the script or log. An SSH
   private key or already configured SSH agent can be used instead.
3. Run with Windows PowerShell 5.1 (this installed WinSCP assembly is not
   compatible with PowerShell 7's newer .NET runtime):

   ```powershell
   powershell.exe -NoProfile -File .\Invoke-FileTransferWinSCP.ps1 -InputFile 'C:\FileTransfer\file-transfer_input_aug26.csv'
   ```

   The filename contains no year, so the current year is used by default. For a
   prior/future-year file, pass `-Year 2027` explicitly.

WinSCP's .NET assembly takes explicit connection options; it does not load a GUI
saved-site record as a connection object. The safest setup is to copy the host,
username, port, host-key fingerprint, and private-key path from the saved site,
while keeping the password out of the config file.

## Short test plan

1. Use non-production test input/output folders in the config.
2. Use a tiny file named for a valid date, such as `file-transfer_input_aug26.csv`.
3. Run the script and confirm the upload appears in the test input folder.
4. Manually copy a file with that same name into the test output folder; confirm
   the script waits for a stable, nonzero size and renames it correctly.
5. Repeat with the final target already present; confirm the script exits with an
   error and does not overwrite it.
6. Repeat with the remote input already present; confirm it is not overwritten.
7. Test a short timeout and an invalid name such as `file-transfer_input_august26.csv`.
8. Enable `DownloadOutput` only in the test config and verify the local download.
9. Review the run log under `%LOCALAPPDATA%\FileTransfer-WinSCP\Logs` before switching the
   two remote folder values to production.

## Daily AWS automation

`Invoke-FileTransferDaily.ps1` checks this exact object for the current date:

```text
s3://<S3_BUCKET>/<USER_PREFIX>/file-transfer_input/file-transfer_input_<mon><day>.csv
```

When present, it downloads and size-validates the input, starts the WinSCP
workflow, and downloads the renamed result to Downloads. It then uploads
`file-transfer_matches_YYYYMMDD.csv` to `<USER_PREFIX>/bankruptcy_candidates`, refreshes the
date-specific `daily_unmatched_candidates_today` Athena view, runs the requested
view SELECT and final exclusion/enrichment query in order, downloads
`bk_candidates_YYYYMMDD.csv`, and publishes that file to `<USER_PREFIX>/bk_file`.

Only after every stage succeeds does it write a per-date completion marker under
`%LOCALAPPDATA%\FileTransfer-WinSCP\State`. Repeated checks for a completed date do nothing.
Interrupted runs resume from matching existing FileTransfer/S3 outputs without overwriting
conflicting files.

Safe check-only test:

```powershell
powershell.exe -NoProfile -File .\Invoke-FileTransferDaily.ps1 -CheckOnly
```

Preview scheduled-task registration:

```powershell
powershell.exe -NoProfile -File .\Install-FileTransferDailyTask.ps1 -WhatIf
```

Register it:

```powershell
powershell.exe -NoProfile -File .\Install-FileTransferDailyTask.ps1
```

The hidden per-user task checks every 15 minutes from 7:00 AM through 6:45 PM
local time and exits silently on weekends. It runs only while this user is logged
in. The AWS `<AWS_PROFILE>` session must still be valid; an expired AWS token is
logged as an error and is never treated as a successful run.
