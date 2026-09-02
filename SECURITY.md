# Security and Data Handling

This public repository is source-only. It is not an approved location for
operational, company-confidential, customer, or credential data.

## Never commit

- Passwords, API keys, access tokens, cookies, SSH private keys, or DPAPI exports.
- AWS account identifiers, live bucket/prefix configuration, SFTP usernames, or
  verified host-key fingerprints unless explicitly approved for source control.
- Oracle, Redshift, PACER, Freshdesk, or Edit Tool credentials and session data.
- Company workbooks, CSV files, query exports, ticket contents, court documents,
  screenshots, attachments, logs, or local databases.
- Case-level SAFE numbers, company IDs, case numbers, or production action queues.

## Configuration

Use environment variables, ignored runtime configuration, or approved OS-backed
credential storage. Committed configuration must contain obvious placeholders.

## Production changes

SQL and automation in this repository are not authorization to change production.
Retain prechecks, row-level review, explicit approval, and post-checks. Legal
Filings, SOS, and Officers remain AWS/Redshift-led during migration unless the
operating model is explicitly changed.

## Before every push

Review `git diff --cached`, run the repository audit script when available, and
confirm that only intended source files are staged. If a secret is committed, do
not merely delete it in a later commit: revoke or rotate it and remove it from Git
history before pushing.
