@{
    # Fill these in before running. Do not put a password in this file.
    Protocol              = 'Sftp' # Sftp, Scp, Ftp, Webdav, or S3
    HostName              = '<SFTP_HOST>'
    PortNumber            = 22
    UserName              = '<SFTP_USERNAME>'
    SshHostKeyFingerprint = '<SFTP_HOST_KEY_FINGERPRINT>'

    # Optional: leave blank when using password authentication or an SSH agent.
    SshPrivateKeyPath     = ''

    # Optional DPAPI-encrypted credential created by Save-FileTransferCredential.ps1.
    CredentialFile       = '%LOCALAPPDATA%\FileTransfer-WinSCP\file_transfer-sftp-credential.clixml'

    RemoteInputDirectory  = '/input'
    RemoteOutputDirectory = '/output'
    LocalDownloadDirectory = '%USERPROFILE%\Downloads'

    PollIntervalSeconds   = 15
    TimeoutMinutes        = 30
    StabilityWaitSeconds  = 10
    DownloadOutput        = $true

    # The script auto-detects the installed assembly. Set this only if needed.
    WinSCPAssemblyPath    = ''
    LogDirectory          = '%LOCALAPPDATA%\FileTransfer-WinSCP\Logs'
}
