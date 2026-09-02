---
name: data-ops
description: Data Operations US Data Team operational context for Oracle, Redshift/AWS migration, Edit Tool automation, legal filings, SOS, officers, bankruptcy, group structure, branch/HQ, and validation workflows. Use when Codex helps <OPERATOR> with Data Operations SQL, Oracle or Redshift queries, Edit Tool actions, migration validation, legal filings, SOS/officer backfeed checks, bankruptcy matching, group structure edits, HQ swaps, branch moves, or related data-quality investigations.
---

# Data Operations Data Ops

Use this skill for Data Operations US Data Team work. Keep actions practical, query-driven, and validation-focused.

**Workspace:** `C:\Users\<USERNAME>\Projects\data-operations-workspace` — open or `move_agent_to_root` here before substantive work. Run `/data-ops-preflight` at session start.

## Current Operating Model

- Treat Oracle as an operational database and validation target.
- Treat Redshift/AWS as the active migration/data-vault side for Legal Filings, SOS, and Officers.
- For Legal Filings, SOS, and Officers during the current migration, do not assume old Oracle edit procedures/packages work. Validate AWS/Redshift outputs and next-day Oracle backfeeds instead.
- For group structure, branch/HQ, and company relationship work, Oracle packages and the Edit Tool may still be relevant, but use pre-checks and post-checks before any state-changing action.
- Do not store or print credentials. Check only whether credential environment variables are present.

## Default Response Shape

For non-trivial Data Operations work, use:

1. Plain-English business explanation
2. Tables/packages/systems involved
3. Risk and side-effect notes
4. Pre-check SQL
5. Action path, if approved and safe
6. Post-check SQL
7. Batch or automation improvement

## Database Access

Oracle local connection pattern:

- Oracle client: `C:\Users\<USERNAME>\Documents\Codex\oracle-instant-client\instantclient_23_0`
- DSN commonly used: `<ORACLE_HOST>:1521/<ORACLE_SERVICE>`
- Credentials are expected in `ORACLE_USER`, `ORACLE_PASSWORD`, and optionally `ORACLE_DSN`, often stored in the Windows user environment.
- Smoke-test with `work\test_oracle_connection.py` when available.

Redshift prod connection pattern:

- Host: `redshift.dv.example.invalid`
- Port: `5439`
- Database: `dev`
- Credentials are expected in `REDSHIFT_PROD_USER` and `REDSHIFT_PROD_PASSWORD`.
- Smoke-test with `work\test_redshift_connections.py prod` when available.

Redshift test connection pattern:

- Host: `dataacquisitionuk-test.cldp5jjlewlk.eu-west-1.redshift.amazonaws.com`
- Port: `5439`
- Database: `data_vault_test`
- Credentials are expected in `REDSHIFT_TEST_USER` and `REDSHIFT_TEST_PASSWORD`.

## Edit Tool Automation

Use Chrome when existing browser session/cookies are needed. The internal Edit Tool host is safe:

`http://<EDIT_TOOL_HOST>/`

For group structure add-company actions:

1. Navigate to `/web/EditToolLive/GroupStructure/Index/<root_safe_number>`.
2. Select the root/parent node.
3. Fill only `#input_safenumber` for US companies unless the user gives more fields.
4. Click `#add_company`.
5. Accept the browser-native JavaScript confirm dialog.
6. Wait for completion and verify the target safe number appears in the persisted tree.

Known reliable confirm handling:

- Start a one-time Windows UI Automation helper that invokes the `OK` button on a dialog whose title includes `<EDIT_TOOL_HOST> says`.
- Then click `#add_company`.
- Verify the tree after the page reloads.

Known duplicate-add behavior:

- Backend may return `ORA-20003: SafeNumber=<...> already exists ...`.
- The page can temporarily show an unsaved jsTree node such as `j1_8`.
- Recovery: reload the group page and verify the persisted tree count.

Before building or actioning group structures, include operational checks in the action list:

- Branch count for each proposed root/subsidiary, usually with `reporting_utils.fn_br_count_for_hq(a.safe_number) AS cnt_br`.
- Whether the company already has a group/company node in `core_data.group_structure`, especially a root/self node for that SAFE number.
- Whether the Edit Tool selected-company panel shows a populated company number/company ID for the node.
- Treat presence of branches as presence of a company ID. If `cnt_br > 0`, expect the company to need the more careful/root-aware workflow even if the full group page has not been opened yet.
- Whether the candidate is already a root of its own group or has branches/subgroup members. These cases are slower than a simple add because the whole existing node/subtree may need to be moved rather than added as a fresh child.

Known root/subtree move workaround:

- If the subsidiary being moved already has a root node/company ID/branches and the Edit Tool page is not exposing the move fields cleanly, open the subsidiary's group-structure page or refresh the root page for that SAFE number.
- Add a temporary bogus company node under the subsidiary root using a harmless placeholder company name and `Add company`.
- Confirm the add and wait until the placeholder child appears under the root in the tree.
- Select the temporary bogus node and remove it. After the page refresh/populates, the real root node details should show with company number and SAFE number populated.
- Select the real root node, then use `Move Group to new Safe Number` at the bottom of the page with the target/root SAFE number.
- Refresh either the subsidiary group page or the target root page after the move; both should show the same resulting two-node/subtree state once Oracle/Edit Tool has refreshed.
- This workaround appears to force the Edit Tool/Oracle grouping state to materialize a movable subtree for an existing root node. Treat it as required for root-node moves, not for ordinary add-company actions.

Known backend group-structure execution paths:

- Full end-to-end skill (inventory → gap classify → remove null SAFE → creates → ADD/MOVE packs): **`entity-group-structure-workflow`** (mirrored in repo `docs/group-structure/` and `.cursor/skills/`).
- For a source report that is already `location_type = 1` and has a company ID or branches, use the Edit Tool backend equivalent of `Move Group to new Safe Number`: `EDITING_API.PKG_ENTITY_GROUP.MOVE_TO_NEW_SAFE_NUMBER(i_safe_number => <target_uhc_safe_number>, i_companyid => <source_companyid>)`.
- Drive `MOVE_TO_NEW_SAFE_NUMBER` from a small inline queue or temp table with `source_safe_number` and `target_uhc_safe_number`, then join `core_data.company_relationship` to resolve the active non-branch `companyid` for the source and target. Require `deleted_by_editing_tool is null`, `deleted_by_import is null`, `company_type != 'BRANCH'`, and `source_safe_number != target_uhc_safe_number`.
- For a source report that is `location_type = 1` but has no branches/company ID, use **`EDITING_API.PKG_ENTITY_RELATIONS.SET_COMPANY_RELATION`** (not `PKG_ENTITY_GROUP`): parent ID from `reporting_utils.fn_companyid(<target_uhc_safe_number>)`, `i_companyid => null`, `i_safe_number => <child_safe_number>`, `i_company_type => 'SUBSIDIARY'`, `i_company_country => 'UNITED STATES OF AMERICA'`, `i_expiry_date => add_months(sysdate, 1200)`, `i_is_hidden => 'N'`, `i_dedupe_override => 'N'`. GROUP.set_company_relation triggers full `p_create_group_structure` and can fill tablespace / leave orphans — do not use for ADD.
- **International SAFE ADD:** same RELATIONS call with `i_company_name` + short country (`CAN`/`IRL`/`NLD`/`MEX`/`FRA`/`GBR`). SAFE need not exist in US `company_search_view`. CLEAN = zero `company_relationship` rows; any history (incl. soft-deleted) → `ORA-20003` → **MOVE**.
- **Null-SAFE ADD** (Edit Tool name+country only / Connect NO_COVERAGE): `i_safe_number => null`, full country label (`BARBADOS`, `BAHAMAS`, …).
- To remove a group node (including null SAFE / junk placeholders): `PKG_ENTITY_GROUP.P_REMOVE_SUBTREE(i_companyid)` — not expiry via GROUP `SET_COMPANY_RELATION`.
- These backend paths can replace repetitive browser interaction for reviewed/approved action queues, but still use pre-checks and post-checks. Log each row with `dbms_output`, handle row-level exceptions inside the loop, and commit only after approval.
- Use `MOVE_TO_NEW_SAFE_NUMBER` for existing root/company-ID/subtree moves; use **RELATIONS** `SET_COMPANY_RELATION` for simple loc type 1 reports with no existing group node/company ID; after Company Import, new SAFEs are ADD candidates via RELATIONS.

Known branch separation / promote branch to HQ workflow:

- When a bankruptcy/grouping review determines an existing branch should become its own HQ, do the branch relationship change before the company-data location-type change.
- First hide the active branch relationship with `EDITING_API.PKG_ENTITY_RELATIONS.SET_COMPANY_RELATION(... i_is_hidden => 'Y')`, preserving the existing `core_data.company_relationship` values and only changing hidden state. This marks `deleted_by_editing_tool` / `deleted_by_import` and inserts an `EXCL_PAIR` into `grouping_data.excl_safenos` against the old HQ.
- Then promote the company record itself with `EDITING_API.PKG_ENTITY_DATA.EDIT_COMPANY_DATA`, preserving the existing company fields and only overriding `i_location_type => '1'` plus `i_expiry_date`.
- Expiry gotcha: `date '<today>'` means midnight at the start of the date. If this is run later that same day, the Edit Tool read path may treat the overlay as expired and still show branch/location type 2. Use tomorrow's date or a future timestamp for `i_expiry_date`.
- Verified backend behavior on `<SAFE_001>`: after hiding the branch relationship, active relationship count was 0 and an `EXCL_PAIR` was created against old HQ `<SAFE_002>`; after promoting with future expiry, `P_GET_COMPANY_DATA`, `company_search_view`, and `core_data.company` all read `location_type = 1`.
- Post-checks for this workflow should include active `company_relationship` count for the SAFE, `grouping_data.excl_safenos`, `EDITING_API.PKG_ENTITY_DATA.P_GET_COMPANY_DATA`, `company_search_view`, and `core_data.company.location_type`.

## Migration Validation Defaults

For Legal Filings, SOS, and Officers:

1. Identify the Redshift/AWS source/output table.
2. Validate same-day records in Redshift/AWS.
3. Identify the Oracle target table/view for next-day backfeed.
4. Query Oracle after backfeed.
5. Compare counts, safe numbers, key dates, deleted/manual-edit flags, and sample rows.
6. Report mismatches and likely root-cause candidates.

Do not call old Oracle edit procedures for these three categories unless <OPERATOR> explicitly says the procedure is restored and safe.

## Bankruptcy Candidate Matching Notes

When validating unmatched bankruptcy rows:

- Skip rows whose `validated_candidate` cell is intentionally black-filled. In Excel/openpyxl this can appear as `patternType=solid` with theme black; `rgb=00000000` with no fill pattern is often just the default no-fill state.
- Prefer assigning the SAFE number when defendant name and company name are effectively the same and the company is active `location_type = 1`.
- Do not use `location_type = 2` branch records as validated candidates. If the sheet candidate is a branch, look for the active `location_type = 1` headquarters/legal entity instead.
- If the row candidate is weak, search Oracle using `company_search_view` with plain prefix `company_name LIKE 'PREFIX%'`. Avoid wrapping `company_name` in `upper(...)` because it can prevent index usage and make searches time out.
- Keep Oracle company-search queries simple and close to <OPERATOR>'s normal patterns. Search by one main predicate at a time:
  - `where safe_number = 'US...'`
  - `where company_name like 'PREFIX%'`
  - optional `and state = 'FL'`
  - `where corp_file_key = 'STATECHARTER'` when a charter/business number was found from OpenCorporates or a state registry
  - `where hq_safe_number = 'US...'` only for branch/HQ or grouping investigations
  Do not start with a combined broad search. A heavier combined query with address `LIKE`, multiple `OR` predicates, branch-count functions, or group-structure flags is a last resort only after the normal safe-number/name/state/corp-file-key searches have been exhausted.
- Prefer the exact legal-name LIKE result over merely related names. For example, if the defendant is `BC BUFFALO LLC`, `company_name LIKE 'BC BUFFALO%'` may return `BC BUFFALO HOSPITALITY LLC`, but the exact `BC BUFFALO LLC` result is the valid candidate and the hospitality record should be treated as a different entity.
- Include legal-name variants:
  - `AND` vs `&`, for example `J AND B...` and `J & B...`
  - punctuation differences
  - spacing differences, for example `WINFIT` vs `WIN FIT`
  - common abbreviations such as `CR` vs `CRESCENT`
- Treat numeric tokens in real-estate/entity names as material. Do not fuzzy-match `423 PINE CR LLC` to `413 PINE CR LLC` or `1021 MAPLE CRESCENT LLC` to `10 12 MAPLE CRESCENT LLC`; search the defendant name directly.
- Use OpenCorporates or equivalent public-source lookup when the name/state relationship is unclear. Generate search variants for `AND`/`&`, no-space ampersands such as `J&B`, suffix-trimmed names, and defendant-state/company-state jurisdiction filters when useful. A valid BK candidate may be a foreign-registered report in another state if public registry evidence ties it to the defendant's domestic/foreign registration chain.
- For bankruptcies, prefer candidate and defendant to match name and state. Accept cross-state candidates only when evidence supports that the report corresponds to the same legal entity or foreign/domestic registration pair.
- If evidence is weak, leave `validated_candidate` blank and put the row in the review/creation list rather than forcing a match.
- If the debtor appears valid but no acceptable active `location_type = 1` report exists in `company_search_view`, either put `Create` in `validated_candidate` or return a separate creation list. <OPERATOR> can create the report, then the bankruptcy can be attached to that new SAFE number.
- Do not confuse creation-needed rows with skip rows. Use black-fill/skip for DBA/alias-only rows, consumer bankruptcies, duplicate rows, or events already represented in `core_data.bankruptcy`; use `Create` for valid business debtor rows where the missing piece is a Data Operations company report.
- If `alternate_case` is duplicated in the workbook, inspect the duplicate rows together. The row whose defendant name has a legal-form ending such as `INC`, `LLC`, `CORP`, `LP`, `LTD`, etc. is often the true legal debtor row; the duplicate without a legal form may be a DBA/alias row.
- If no duplicate row has a legal-form debtor name, or if duplicate rows are ambiguous, use PACER and Oracle bankruptcy history before assigning.
- Check prior bankruptcy matches with:
  `select * from core_data.bankruptcy where other_case_number = '<alternate_case>';`
  Treat this as a candidate-history lookup only. Do not skip solely because `other_case_number` exists; case numbers can repeat across different courts. Before calling a row already loaded, confirm court/case context matches the current row, using `cust_court`/`courtid`, filing date, debtor/legal name, safe number, and event/release date. If the case number exists only in a different court or different debtor context, keep the row in play as a distinct bankruptcy case.
  If the same court/case context is already matched as an initial filing with no new release/conversion/discharge data in the current workbook row, skip or black-fill the row. If the current workbook row contains a release date or other new filing event missing from the matching prior bankruptcy rows, it may still be valid to populate the matching SAFE number.

Local helper:

- From the current Data Operations workspace, run `python open_corporates_name_search.py "COMPANY NAME" --jurisdiction us_fl --jurisdiction us_ga` to produce OpenCorporates search URLs and variants.

## Google Alerts Bankruptcy Review Notes

When reviewing Freshdesk/Google Alert tickets for missing bankruptcies:

- Use Chrome when the helpdesk session or paywalled/news site cookies matter.
- Extract the article links from the alert ticket, then filter for actual business bankruptcy, insolvency, restructuring, receivership, liquidation, or Chapter 11/7 signals. Treat generic closures, Social Security insolvency stories, acquisitions, lawsuits, and non-business headlines as noise unless they name a debtor.
- Identify the exact legal debtor from the article before querying. For franchise stories, separate franchisor/brand names from the franchisee/debtor legal entities. If the article says an affiliate did not file, do not mark that affiliate as missing just because it is related.
- Query Oracle using <OPERATOR>'s normal simple sequence: `company_search_view` by exact safe number if given, otherwise `company_name LIKE 'PREFIX%'`, then optional state or `corp_file_key` if public registry data supports it.
- Verify the company candidate is an active `location_type = 1` headquarters/legal entity before treating it as the report to use.
- Check `core_data.bankruptcy` by debtor-name pattern and by candidate SAFE number. Use `other_case_number`, filing date, and release/conversion/discharge fields to distinguish already-covered filings from genuinely missing later events.
- Classify each alert lead as `already covered`, `missing bankruptcy`, `create report`, `review`, or `noise`. Include the debtor legal name, SAFE number if found, case number if found, filing/release date, and why it was classified that way.
- If the alert is recent and the article is vague, use PACER Case Locator or article court/docket details to confirm the debtor name before recommending a new bankruptcy record.
- For bankruptcy-derived group-structure leads, use PACER Associated Cases when the lead/root is unclear. A formal associated-cases result is strong linkage evidence. If PACER says there are no case associations, downgrade confidence even when cases share filing date, judge, attorney, address, or article context; those signals can still support review, but they do not confirm the root/lead by themselves.

## PACER DBA/Alias Verification Notes

For bankruptcy rows where DBA/legal-name status is unclear:

- Use `alternate_case` as the PACER Case Locator case-number input after replacing the zero immediately after the two-digit year prefix with a dash (`YY0NNNNN` becomes `YY-NNNNN`).
- Search by case number in PACER Case Locator, then inspect the case summary/party information to distinguish debtor legal name from DBA/alias names.
- If the candidate is only a DBA/alias and not the debtor legal name, do not assign the bankruptcy to the DBA record.
- If PACER shows the debtor is a consumer/person bankruptcy, skip or black-fill the row rather than assigning a business SAFE number.
- If PACER search results show a different legal debtor with a legal form, use that as evidence that the sheet row may be an alias/DBA row.
- PACER credentials can be supplied through environment variables `PACER_USERNAME` and `PACER_PASSWORD`; do not print them. If MFA or a login challenge appears, pause for <OPERATOR> to complete it.
- Prior PACER automation exists in `C:\Users\<USERNAME>\Documents\Codex\2026-05-27\files-mentioned-by-the-user-pacerparser\pacerparser_auto.py`; it uses PACER Case Locator, `PACER_USERNAME`, `PACER_PASSWORD`, optional client code, and has a `--case-number` path.

Local helper:

- From the current Data Operations workspace, run `python pacer_case_number_helper.py <ALTERNATE_CASE>` to format an `alternate_case` value as a PACER case-number search value.

## Detailed Reference

Read `references/data_operations_context.md` when the task needs detailed domain knowledge, object lists, package names, SQL examples, bankruptcy categories, SOS/officer details, or migration planning guidance.
