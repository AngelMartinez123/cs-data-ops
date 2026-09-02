# Remote Windows deployment

Use an always-on Windows VM or remote desktop host. Run all setup commands while
signed in as the same Windows account that will own the scheduled tasks.

## Required software

1. WinSCP, including `WinSCPnet.dll`.
2. AWS CLI v2.
3. Node.js plus `npm install -g aws-azure-login`.
4. Python 3 plus `python -m pip install boto3`.

## Deployment

1. Extract this package to a stable folder such as `C:\FileTransferAutomation`. Do not run
   it from Downloads or a temporary folder.
2. Open **Windows PowerShell 5.1** in that folder and run:

   ```powershell
   powershell.exe -NoProfile -File .\Test-FileTransferRemotePrerequisites.ps1
   ```

3. Configure and authenticate the AWS `<AWS_PROFILE>` profile on this remote
   machine. Do not copy temporary AWS credential files from another computer:

   ```powershell
   aws-azure-login.cmd --configure --profile <AWS_PROFILE>
   aws-azure-login.cmd --profile <AWS_PROFILE> --mode=gui --no-sandbox --no-prompt
   aws sts get-caller-identity --profile <AWS_PROFILE>
   ```

4. Create the remote machine's DPAPI-encrypted SFTP credential:

   ```powershell
   powershell.exe -NoProfile -File .\Save-FileTransferCredential.ps1
   ```

5. Run a read-only S3 check:

   ```powershell
   powershell.exe -NoProfile -File .\Invoke-FileTransferDaily.ps1 -CheckOnly
   ```

6. Register both tasks to run even when the user is logged off. The installer
   prompts once for the remote Windows account password; Task Scheduler stores it
   using Windows protected task credentials:

   ```powershell
   powershell.exe -NoProfile -File .\Install-FileTransferRemoteTasks.ps1
   ```

7. In Task Scheduler, verify `FileTransfer Daily Automation` and `Data Operations AWS Refresh`
   show **Run whether user is logged on or not**. Run `Data Operations AWS Refresh`
   once, then run `FileTransfer Daily Automation` once. A missing daily S3 input is a normal
   successful no-op.

8. Check logs under `%LOCALAPPDATA%\FileTransfer-WinSCP\Logs` and state under
   `%LOCALAPPDATA%\FileTransfer-WinSCP\State` for the task-owning account.

## Cutover

Disable the two tasks on the original computer only after the remote tasks have
completed one full weekday run. This prevents duplicate workers during testing.

The final durable output remains in
`s3://<S3_BUCKET>/<USER_PREFIX>/bk_file/`. The remote Downloads folder is not
the physical computer's Downloads folder.
