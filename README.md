# CS Data Ops

Public-safe examples of reusable data-operations code, query patterns, runbooks,
tests, and agent guidance. The repository is designed for use from both Cursor
and Codex while keeping operational data, company infrastructure, and credentials
outside Git.

## Repository contents

- `automation/`: repeatable orchestration and scheduled-job source.
- `automation/file-transfer/`: sanitized file-transfer, WinSCP, AWS, and Athena automation.
- `scripts/`: bankruptcy, branch/HQ, Company Import, PACER, and QC helpers.
- `sql/`: reusable query patterns. Historical result sets and production procedure
  snapshots are deliberately excluded.
- `docs/`: operational runbooks and workflow references.
- `.cursor/`: shared Cursor rules and sanitized workflow skills.
- `tests/`: checks that do not require committing credentials or production data.

## Security boundary

Never commit credentials, cookies, browser state, PACER responses, database
exports, live workbooks, CSV inputs, case-level evidence, ticket extracts, logs,
or generated output. See `SECURITY.md` and `.gitignore`.

The example file-transfer configuration files contain placeholders. Copy them to the ignored
runtime names before local use:

```powershell
Copy-Item automation/file-transfer/FileTransfer.Daily.config.example.psd1 automation/file-transfer/FileTransfer.Daily.config.psd1
Copy-Item automation/file-transfer/FileTransfer.WinSCP.config.example.psd1 automation/file-transfer/FileTransfer.WinSCP.config.psd1
```

Fill the runtime copies only with values approved for the machine. Keep passwords
in the documented secure credential mechanism or environment variables, never in
repository files.

## Operating model

- Oracle-style systems are represented as operational databases and validation targets.
- Migration examples treat legal filings, registrations, and officers as warehouse-led
  workflows with downstream database validation.
- Bankruptcy, group-structure, and branch/HQ work must retain read-only prechecks,
  explicit approval before state-changing actions, and post-check validation.
- The examples preserve branch-versus-headquarters validation before matching events.
- Placeholder values such as `<SAFE_001>`, `<AWS_PROFILE>`, and `<ORACLE_HOST>` must
  be supplied locally and must not be replaced with live values in committed files.

## Local setup

1. Clone the repository into an approved local workspace.
2. Create a Python virtual environment outside committed paths.
3. Install the dependencies used by the relevant script.
4. Configure credentials through environment variables or approved OS-backed
   credential storage.
5. Run read-only preflight checks before database or AWS work.
6. Keep all inputs and outputs in ignored `work/` and `outputs/` directories.

## Cursor and Codex

Cursor and Codex can edit the same checkout. Git records changes independently of
which tool produced them. The `.cursor` material supplies shared workflow context;
Codex-specific application state, sessions, secrets, and memory databases are not
part of this repository.
