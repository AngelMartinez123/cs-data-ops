@{
    # Copy this example and replace placeholders with approved local values.
    AwsProfile       = '<AWS_PROFILE>'
    AwsRegion        = '<AWS_REGION>'
    S3Bucket         = '<S3_BUCKET>'
    S3Prefix         = '<FileTransfer_INPUT_PREFIX>'
    BankruptcyCandidatesPrefix = '<BANKRUPTCY_CANDIDATES_PREFIX>'
    BkFilePrefix     = '<BK_FILE_PREFIX>'
    BkOutputNameTemplate = 'bk_candidates_{0}.csv'
    AthenaCatalog    = 'AwsDataCatalog'
    AthenaDatabase   = '<ATHENA_DATABASE>'
    AthenaWorkGroup  = '<ATHENA_WORKGROUP>'
    LocalInputFolder = '%USERPROFILE%\Downloads'
    StateDirectory   = '%LOCALAPPDATA%\FileTransfer-WinSCP\State'
    LogDirectory     = '%LOCALAPPDATA%\FileTransfer-WinSCP\Logs'
}
