# Initial Curation Manifest

## Included

- Reusable Python and PowerShell scripts from the Data Operations workspace.
- Selected reusable SQL patterns with case-level SAFE literals replaced by
  placeholders.
- File-transfer orchestration source with live infrastructure configuration converted to
  ignored runtime files and sanitized examples.
- Group-structure documentation and Cursor workflow rules/skills.
- Existing source-only tests.

## Deliberately excluded

- The original `work/` and `outputs/` trees.
- CSV, XLSX, XLSM, ZIP, log, state, and generated cache files.
- Lambda deployment ZIP and live policy/trust/trigger configuration.
- Historical SQL worksheets dominated by production identifiers or query results.
- Production stored-procedure snapshots because they may contain proprietary source
  and are not necessary for the reusable toolkit.
- The entire Codex application directory, including authentication state, secrets,
  sessions, browser state, attachments, logs, SQLite databases, and memories.

## Sanitization performed

- Replaced personal Windows username paths with `<USERNAME>` placeholders.
- Replaced email addresses with generic placeholders.
- Replaced selected internal hosts with explicit host placeholders.
- Replaced live-looking SAFE identifiers with numbered placeholders.
- Replaced live FileTransfer AWS/S3/SFTP configuration with example placeholders.

The published version uses generic service, schema, package, and workflow names.
