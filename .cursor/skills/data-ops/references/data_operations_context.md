# Data Operations AI Agent Context Document

**Purpose:** Give an artificial intelligence agent enough background to understand <OPERATOR>'s Data Operations work environment, workflows, data concepts, automation opportunities, and known backend patterns.

**Intended use:** SQL generation, workflow automation, SOP creation, backend package analysis, Oracle/AWS migration planning, data quality investigation, bankruptcy matching, legal filing cleanup, group structure work, and edit-tool automation.

---

## 1. User / Role Context

<OPERATOR> works at Data Operations on the US Data Team as a Government Data Analyst / Legal Filings data analyst.

Core work areas include:

- Bankruptcy processing and matching
- Legal filings maintenance
- Branch/HQ and group structure corrections
- SOS record correction
- Vendor file ingestion support
- Data quality investigations
- Customer issue research
- Oracle SQL analysis
- AWS Athena workflows
- Semi-automation of manual data workflows

<OPERATOR> has strong practical SQL knowledge and business-process knowledge. He often needs AI help turning manual investigation steps into safer, repeatable SQL or workflow playbooks.

Typical working style:

- Wants practical scripts and clear explanations
- Prefers direct, usable SQL patterns
- Values business logic explanations before code
- Often works from existing Oracle packages and procedures
- Wants to reduce repetitive UI work in the edit tool
- Wants backend-equivalent procedures where safe

---

## 2. Core Systems

### Oracle

Primary operational database environment.

Common schemas:

```text
CORE_DATA
EDITING_API
GROUPING_DATA
REPORTING_UTILS
<USERNAME>
LOAD_SOURCE_VENDOR_NEG
```

Common Oracle use cases:

- Legal filing analysis
- Bankruptcy correction
- Group structure review
- Edit tool backend procedure calls
- SOS data review
- Branch/HQ investigation
- Re-rating and downstream refresh checks

<OPERATOR> often has SELECT access, but limited direct DML permissions. Data-changing workflows should usually be done through known edit-tool packages/procedures rather than raw table updates.

### AWS / Athena / S3

AWS is used for newer bankruptcy workflows and daily file movement.

Common uses:

- Athena queries
- S3 file drops
- Bankruptcy unmatched outputs
- Auto-match outputs
- FileTransfer input/output handling
- Refresh workflows
- Data Vault / mart-style downstream models

---

## 3. High-Level Business Domain

Data Operations maintains company credit/reporting data. <OPERATOR>'s work focuses heavily on government/legal data, especially bankruptcies.

Key business problem:

Legal filings may be attached to the wrong entity, especially when a bankruptcy is filed under a branch but should roll up to the HQ/parent entity.

Important entity concepts:

- SAFE number: company identifier, often like `<SAFE_003>`
- HQ safe number: parent/headquarters company identifier
- Branch: child/location record under a parent/HQ
- Subsidiary: company relationship type that may sit between branch and ultimate parent
- Group structure: hierarchy connecting companies

---

## 4. Key Oracle Objects

Frequently used tables/views:

```sql
core_data.company
core_data.bankruptcy
core_data.lien
core_data.judgment
core_data.ucc
core_data.company_relationship
core_data.group_structure
core_data.company_sos
core_data.branches_with_parents
core_data.tpd_grouping

editing_api.company
editing_api.bankruptcy
editing_api.company_relationship
editing_api.company_sos
editing_api.tpd_grouping

company_search_view
core_data.mv_safe_numbers_redirect
mart_us_legacy.safe_numbers_redirect
```

Common columns:

```text
SAFE_NUMBER
HQ_SAFE_NUMBER
COMPANY_NAME
COMPANYID
PARENTID
CS_COMPANY_ID
COMPANY_TYPE
DELETED_BY_EDITING_TOOL
DELETED_BY_IMPORT
FILING_DATE
RELEASE_DATE
CASE_NUMBER
OTHER_CASE_NUMBER
COURTID
DEFENDANT_TYPE
```

---

## 5. ET vs CORE Mental Model

A major recurring concept is the distinction between:

```text
EDITING_API = edit-tool working/staging layer
CORE_DATA = production/core layer
```

Many backend packages update both ET and CORE. Some procedures first sync ET from CORE, apply changes, then push back to CORE.

When building automation, always determine:

1. Is the row in ET, CORE, or both?
2. Which table is authoritative for this workflow?
3. Does the package sync ET from CORE?
4. Does the package push ET back into CORE?
5. Does the procedure commit internally?
6. Does it enqueue safe numbers or rebuild downstream artifacts?

General rule:

```text
Use approved packages where possible instead of direct DML.
```

---

## 6. Legal Filings Backend Knowledge

Key package:

```sql
EDITING_API.PKG_EDIT_LEGAL_FILINGS
```

Important concepts:

- Row-level hide/show actions are separate from company-level recalculation.
- The edit tool checkbox hide/show is usually just a soft delete / un-delete action.
- The Recalculate Legal Filings button maps to a heavier backend rebuild procedure.

### Row-Level Actions

General wrapper:

```sql
editing_api.pkg_edit_legal_filings.hide(
    i_safe_number => 'US...',
    i_id          => <filing_id>,
    data_type     => 'BK',
    o_cursor      => :rc
);
```

For bankruptcies, the internal row-level routine is conceptually:

```sql
hide_show_bankruptcy(...)
```

Known behavior:

- For BK, package can pull rows from `core_data.bankruptcy` by ID and merge into ET if needed.
- This means loops should usually drive from CORE bankruptcy IDs, not only ET IDs.

### Company-Level Recalculation

Important procedure:

```sql
editing_api.pkg_edit_legal_filings.after_show_or_hide(
    i_safe_number => 'US...'
);
```

This is the backend equivalent of the edit tool's Recalculate Legal Filings button.

It may:

- Insert into `DET_LF_UPDATE_TABLE`
- Refresh `MV_FILINGS_BANKRUPTCY`
- Recalculate UCC cautionary flags
- Rebuild company filings
- Enqueue safe number
- Commit changes

### Best Batch Pattern

Preferred automation pattern:

```text
1. Pre-check rows
2. Perform all row-level hide/show changes
3. Run after_show_or_hide once per safe number
4. Post-check results
```

Avoid this pattern:

```text
hide row 1 -> recalc
hide row 2 -> recalc
hide row 3 -> recalc
```

Use this pattern:

```text
hide row 1
hide row 2
hide row 3
recalc once
```

This reduces queue spam and expensive repeated rebuilds.

---

## 7. Bankruptcy Workflows

### Daily Bankruptcy Workflow

Typical daily workflow includes:

1. Run unmatched bankruptcy query in AWS Athena
2. Save/export unmatched output
3. Drop unmatched output into S3 path
4. Run FileTransfer input query
5. Place FileTransfer input CSV into SFTP `/input`
6. Wait for output in `/output`
7. Rename FileTransfer matches file
8. Drop FileTransfer matches into RDC / S3 path
9. Run auto-match query
10. Generate auto-match CSV
11. Refresh related views
12. Import outputs through edit tool or workflow
13. Next-day rerating / QC

Known naming patterns:

```text
unmatched_BK_AWS_MMMDD
FileTransfer_input_MMMDD
auto_match_MMMDD
FileTransfer_Matches_YYYYMMDD
```

### Bankruptcy Matching Logic

Important fields:

```text
safe_number
hq_safe_number
case_number
other_case_number
courtid
filing_date
release_date
defendant_type
filing_types
```

Common filter:

```sql
coalesce(deleted_by_editing_tool, deleted_by_import) is null
```

Business focus is usually business bankruptcies, not consumer bankruptcies. `defendant_type = 'B'` is commonly used.

---

## 8. Bankruptcy Cleanup Categories

A major automation project is classifying large bankruptcy candidate sets into manageable buckets.

### Category 1: Exact Name + HQ Exists + HQ Has No BK

Very high confidence. Often candidate for HQ/branch correction.

### Category 2: Address Match + HQ Exists + HQ Has No BK

High confidence. Address matching can be stronger than name matching.

### Category 3: Same Name + Same State + HQ Has No BK

Moderate confidence. Needs caution for franchises/generic names.

### Category 4: Branch BK and HQ BK Same Case

Very high-value cleanup category.

Logic:

```text
Branch has BK
HQ has BK
Same other_case_number
Same courtid
```

Preferred action:

```text
Hide branch BK
Keep HQ BK
Run one recalculation per branch safe number
```

This is bankruptcy cleanup, not necessarily an HQ swap.

### Category 5: Branch BK, HQ Exists, Different State

Requires assisted review. Could be legitimate, incorrect branch relationship, or wrong HQ.

### Category 6: No HQ Exists

May require HQ creation or leaving untouched depending on business rule.

### Category 7: Multiple HQ Candidates

Dangerous. Usually not auto-safe.

---

## 9. Group Structure / Branch-HQ Backend Knowledge

Key package:

```sql
EDITING_API.PKG_ENTITY_RELATIONS
```

This package is extremely important for automating group structure workflows.

It can:

- Create HQ records
- Add branches
- Move branches
- Swap HQs
- Update CORE and ET relationship tables
- Update TPD grouping
- Rebuild group structure
- Update company location type
- Enqueue safe numbers

### Important Procedures

#### Create HQ

```sql
p_create_hq(i_safe_number)
```

Creates a new HQ relationship record when a valid company exists but no active relationship record exists.

#### Move Branch

```sql
p_move_branch(i_companyid, i_parentid, i_expiry_date default sysdate + 1)
```

Moves a branch/company relationship record under a different parent.

#### Set Company Relation

```sql
set_company_relation(...)
```

Core procedure for creating/updating a relationship record.

Can update both `EDITING_API.COMPANY_RELATIONSHIP` and `CORE_DATA.COMPANY_RELATIONSHIP`.

May also:

- Update location type
- Rebuild group structure
- Update TPD grouping
- Insert exclusions when hiding a branch

#### Bulk Safe Number Addition

```sql
p_bulk_safe_number_addition(
    i_parent_id,
    i_safe_number_string,
    i_parent_safe_number,
    o_ref_cursor
)
```

Allows adding multiple branch safe numbers from a comma-separated list.

Useful for reducing repetitive branch-add UI work.

#### Swap HQ

```sql
p_swap_hq(
    i_safe_number_oldhq,
    i_safe_number_newhq
)
```

Used when a current branch should become the HQ and the old HQ should become a branch.

Known behavior:

- Validates old HQ is HQ/subsidiary
- Validates new HQ is branch or not yet in company relationship
- Updates company relationship in CORE and ET
- Updates company types
- Updates parent IDs
- Updates TPD grouping
- Updates location types
- Rebuilds group structure
- Enqueues safe numbers

This is powerful but heavy. Use strong pre-checks and post-checks.

---

## 10. Group Structure Workflow

Typical workflow for building or correcting group structure:

1. Search company in `company_search_view` or `core_data.company`
2. Identify HQ and branch candidates
3. Review existing relationship in `company_relationship`
4. Check if target company is already HQ/subsidiary/branch
5. Check for active deleted flags
6. Decide operation:
   - Create HQ
   - Add branch
   - Move branch
   - Swap HQ
   - Hide/remove relationship
7. Execute package procedure
8. Rebuild group structure if package does not already do it
9. Verify `group_structure`
10. Verify `branches_with_parents`
11. Verify `company_search_view`
12. Verify location type
13. Queue/re-rate if needed

---

## 11. SOS Backend Knowledge

Key package:

```sql
EDITING_API.PKG_EDIT_COMPANY_SOS
```

Main procedure:

```sql
edit_sos(...)
```

Other procedures:

```sql
edit_sos_agent(...)
edit_people(...)
hide_sos(...)
show_sos(...)
hide_sos_agent(...)
show_sos_agent(...)
hide_sos_people(...)
show_sos_people(...)
```

Known behavior:

- `edit_sos` is the main backend path for editing SOS/company rows.
- It syncs ET from CORE.
- It merges changed values into ET.
- It pushes changes back to CORE.
- It updates company charter number.
- It enqueues the safe number.
- It protects manual edits from Equifax/source overwrite behavior.

Safe usage pattern:

```text
1. Query current row from core_data.company_sos
2. Copy full current payload
3. Change only intended fields
4. Call edit_sos
5. Post-check ET and CORE
```

---

## 12. Common SQL / Investigation Patterns

### Find branch reports under an HQ with filings

Example concept:

```sql
select *
from core_data.bankruptcy b
join core_data.branches_with_parents bp
  on bp.safe_number = b.safe_number
where bp.hq_safe_number = 'US...';
```

### Find company and branch context

```sql
select reporting_utils.fn_br_count_for_hq(a.safe_number) as cnt_br,
       case when safe_number in (
           select safe_number
           from core_data.group_structure
           where safe_number is not null
       ) then 'Y' else 'N' end as sn_in_grpstr,
       a.*
from company_search_view a
where hq_safe_number = 'US...';
```

### Preview bankruptcy rows before hide

```sql
select id,
       safe_number,
       case_number,
       other_case_number,
       courtid,
       filing_types,
       filing_date,
       release_date,
       deleted_by_editing_tool,
       deleted_by_import
from core_data.bankruptcy
where safe_number = 'US...'
  and coalesce(deleted_by_editing_tool, deleted_by_import) is null
order by case_number, filing_date, id;
```

---

## 13. Data Quality Issues Already Investigated

### Date Parsing / File Import Issue

Observed issue around June 2026 bankruptcy imports:

- Some filing dates appeared month/day flipped
- Jun 02 and Jun 04 imports looked messy
- Jun 03 parsed correctly
- Suspected difference between CSV and XLSX parsing
- System uses XLSX in normal process
- Question investigated: whether bad CSV uploads caused date parsing errors

Important fields:

```text
CREATE_DATE = import/create date
FILING_DATE = filing date on record
```

Important caution:

When diagnosing date issues, compare source file format, Oracle parsed dates, import dates, and date buckets.

---

## 14. Oracle to AWS Migration Knowledge

<OPERATOR> has asked about Oracle-to-AWS migration in the context of Data Operations moving or mirroring logic into AWS/Data Vault-style environments.

### General Migration Concept

Oracle-to-AWS migration usually involves moving one or more of these layers:

1. Raw source data
2. Operational tables
3. Reporting/mart tables
4. Business logic
5. Stored procedure behavior
6. Materialized views
7. Downstream report outputs
8. Edit-tool behavior

The hard part is rarely just copying rows. The hard part is preserving business meaning.

### Common AWS Targets

Depending on architecture, Oracle data may move into:

```text
Amazon S3
AWS Glue Catalog
Amazon Athena
Amazon Redshift
AWS DMS
AWS Glue ETL
EMR / Spark
Data Vault / mart schemas
```

### Common Migration Pattern

A practical pattern is:

```text
Oracle source
↓
Extract / replicate
↓
S3 raw zone
↓
Glue catalog / Athena external tables
↓
Transform into curated models
↓
Mart / reporting layer
↓
Validation against Oracle
```

### Key Tools

Common AWS services for Oracle migration:

- AWS DMS: replication/change data capture from Oracle
- AWS SCT: schema conversion from Oracle to AWS targets
- S3: raw and curated storage
- Glue: catalog and ETL jobs
- Athena: query engine over S3
- Redshift: warehouse target when performance/concurrency is needed
- Step Functions / Airflow / MWAA: orchestration

### Main Challenges

Important migration challenges:

#### 1. Stored Procedure Logic

Oracle packages are business logic, not just code.

Examples from <OPERATOR>'s environment:

```sql
PKG_EDIT_LEGAL_FILINGS
PKG_ENTITY_RELATIONS
PKG_EDIT_COMPANY_SOS
PKG_FILINGS
```

These procedures often:

- Validate business rules
- Update multiple tables
- Commit internally
- Refresh materialized views
- Enqueue safe numbers
- Rebuild group structures
- Sync ET and CORE

When moving to AWS, this logic must be reimplemented, not merely migrated.

#### 2. Materialized Views

Oracle materialized views may need replacement as:

- Athena CTAS tables
- Glue jobs
- Redshift materialized views
- Spark jobs
- Incremental tables in S3

#### 3. ET vs CORE Semantics

If AWS only receives CORE outputs but not ET staging logic, some manual edit behavior may be lost.

The migration must define:

```text
What is source of truth?
Where do manual edits live?
How do manual edits override vendor/source refreshes?
How are deletes/soft deletes represented?
```

#### 4. Soft Deletes

Data Operations logic heavily uses:

```text
DELETED_BY_EDITING_TOOL
DELETED_BY_IMPORT
DELETED_DATE
DELETED_FLAG
```

AWS models must preserve these semantics.

#### 5. Redirect / Merge Logic

Safe number redirects matter.

Known object:

```sql
core_data.mv_safe_numbers_redirect
mart_us_legacy.safe_numbers_redirect
```

Business issue:

When companies merge, downstream AWS/Data Vault models may need to roll old safe numbers up to surviving safe numbers.

Migration must clarify whether facts are:

- Physically moved to the primary safe number
- Virtually redirected at query/model time
- Preserved under old safe number with redirect mapping

#### 6. Validation

Each migrated object should be validated using:

```text
row counts
safe number counts
filing counts
date ranges
deleted/null flag counts
case-level matching
sample record comparison
known customer/report examples
```

### Useful Migration Questions for AI Agent

When helping with Oracle-to-AWS migration, ask:

1. What Oracle table/view/procedure is being replaced?
2. Is the target Athena, Redshift, S3, or another mart?
3. Is this batch or CDC?
4. Are soft deletes preserved?
5. Are manual edits included?
6. Are merge/redirect rules applied?
7. Are materialized views being refreshed or replaced?
8. What downstream reports depend on this object?
9. What is the validation query against Oracle?
10. What is the acceptable difference threshold?

### Best AI Assistance for Migration

For <OPERATOR>, the AI should help by producing:

- Source-to-target mapping documents
- Oracle vs Athena validation queries
- Migration test plans
- Business logic summaries of Oracle packages
- Replacement pseudocode for Oracle procedures
- Data quality checks
- S3/Athena folder and partitioning recommendations
- SOPs for refresh workflows

---

## 15. Automation Philosophy

<OPERATOR> wants to reduce filler work.

Best automation strategy:

```text
1. Identify repeated manual UI workflow
2. Find backend package/procedure behind it
3. Understand ET/CORE side effects
4. Build pre-check query
5. Build controlled action script
6. Build post-check query
7. Test on one safe number
8. Expand into batch mode
```

Avoid blindly automating:

- Group structure rebuilds
- HQ swaps
- Procedures with internal commits
- Materialized view refreshes
- Bulk deletes/hides
- TPD grouping changes
- Anything that affects customer-facing reports immediately

---

## 16. Preferred AI Response Pattern

When helping <OPERATOR>, use this structure:

```text
1. Plain-English business explanation
2. What tables/packages are involved
3. Risk/side effect notes
4. Pre-check SQL
5. Action SQL/procedure call
6. Post-check SQL
7. Batch/automation improvement if appropriate
```

Keep explanations practical and directly tied to the work.

Do not overcomplicate SOPs with unnecessary safety language unless the workflow is risky.

---

## 17. High-Value Future Automation Ideas

### Bankruptcy Automation

- Daily unmatched query runner
- Auto-match query runner
- FileTransfer input/output file mover
- S3 drop automation
- View refresh automation
- Import/QC validation automation
- Re-rate queue automation

### Legal Filing Cleanup

- Branch/HQ duplicate BK cleanup
- Batch hide/show by safe number
- One recalc per safe number
- Case-level duplicate detection

### Group Structure

- Bulk branch addition
- HQ swap candidate classification
- Branch move recommendations
- Group structure validation report

### SOS

- Controlled field update scripts
- Bulk status correction with pre/post-checks
- Agent/person visibility cleanup

### Migration

- Oracle-to-Athena validation packs
- Source-to-target mapping docs
- Data Vault redirect validation
- Soft-delete preservation checks

---

## 18. Important Rule of Thumb

<OPERATOR>'s work usually becomes easier when the AI turns a messy process into this shape:

```text
Find candidates
↓
Classify confidence
↓
Preview records
↓
Run package-based action
↓
Rebuild/refresh once
↓
Post-check
↓
Document outcome
```

This is the core operating model for future automation.
