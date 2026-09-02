---
name: entity-group-structure-workflow
description: >-
  End-to-end Data Operations US group-structure research and actioning: resolve UHC,
  inventory Oracle relationships, gap-classify subsidiaries (MOVE/ADD/CREATE/REVIEW),
  remove null/bad SAFE nodes, Company Import creates, match newly created SAFEs,
  and Biogen MOVE/ADD SQL packs. Use when <OPERATOR> or a coworker asks for group
  structure under a UHC, EX-21.1 / subsidiary list gaps, remove null SAFE, add
  created companies to a group, MOVE_TO_NEW_SAFE_NUMBER, SET_COMPANY_RELATION,
  p_remove_subtree, or /group-structure.
---

# Data Operations Group Structure Workflow

Full research → classify → pack → (approved) action loop for US group structure.

**Workspace:** `C:\Users\<USERNAME>\Projects\data-operations-workspace`
**Outputs:** `work/YYYY-MM-DD/`
**Preflight:** `/data-ops-preflight` before Oracle work
**Do not commit / execute backend PL/SQL without explicit approval**

Companion: [group-structure-pack](../group-structure-pack/SKILL.md) for workbook generation from a finished candidate CSV.
Details/templates: [reference.md](reference.md) · Example walkthrough: [examples.md](examples.md)

## Decision map (classify first)

| Situation | Action |
|-----------|--------|
| Exact HQ SAFE already under target UHC tree | Skip / already in group |
| Exact HQ SAFE + active non-BRANCH `companyid` | **MOVE** → `MOVE_TO_NEW_SAFE_NUMBER` |
| Exact HQ SAFE, no non-BRANCH relationship | **ADD** → `PKG_ENTITY_RELATIONS.SET_COMPANY_RELATION` (not GROUP) |
| No exact HQ after name normalization | **CREATE** → Company Import, then **ADD** |
| Exact name exists only as `location_type=2` / BRANCH | **REVIEW** (separation / HQ swap) — not CREATE |
| Active USA node under UHC with `cs_company_id` null | **REMOVE** → `p_remove_subtree` |
| Active USA node with bad SAFE prefix (e.g. `WY…`) when scrubbing | **REMOVE** → `p_remove_subtree` |
| Non-US SAFE with **zero** `company_relationship` rows | **ADD (intl SAFE)** — name + country required |
| SAFE known in relationship (even soft-deleted) | **MOVE** if `companyid` exists — ADD hits `ORA-20003` |
| No Connect/report SAFE (EX-21.1 gap) | **ADD (null SAFE)** — name + country only (`i_safe_number => null`) |

Presence of branches ⇒ company ID exists ⇒ MOVE path, not ADD.

**CLEAN ADD check:** `company_relationship` must have **zero rows** for that SAFE (any history, including soft-deleted, blocks ADD with `ORA-20003: SafeNumber=… already exists`). History + `companyid` → **MOVE**.

## End-to-end checklist

```
- [ ] 1. Resolve target UHC SAFE + parent companyid
- [ ] 2. Get subsidiary source list (EX-21.1 / portfolio / research)
- [ ] 3. Inventory current Oracle group under UHC
- [ ] 4. Optional cleanup: null SAFE / bad SAFE removes
- [ ] 5. Gap-classify missing USA names → MOVE / ADD / CREATE / REVIEW
- [ ] 6. Build Company Import for CREATEs (if any); <OPERATOR> imports
- [ ] 7. Pull newly created SAFEs; fold into ADD list
- [ ] 8. Write Biogen MOVE + ADD SQL packs (+ remove pack if needed)
- [ ] 9. <OPERATOR> approves → run → post-check
```

## 1. Resolve target UHC

```sql
SELECT safe_number, company_name, address, city, state, zip, location_type
FROM company_search_view
WHERE safe_number = '<UHC_SAFE>';

SELECT companyid, parentid, cs_company_id, company_name, company_type
FROM core_data.company_relationship
WHERE cs_company_id = '<UHC_SAFE>'
  AND deleted_by_editing_tool IS NULL
  AND deleted_by_import IS NULL;
```

Record: **UHC SAFE**, **parentid/companyid** (e.g. `<SAFE_004>` / `<COMPANY_ID>`), address for creates when source is silent.

## 2. Subsidiary source list

Typical sources: SEC **Exhibit 21.1** HTML, internal lists, Gemini/group research.

For EX-21.1 HTML:
1. Parse entity name + jurisdiction from table rows (not naive line pairing — SEC HTML uses nested tables).
2. Flag USA = US state jurisdictions (Delaware, Texas, …).
3. Write `*_ex211_subsidiaries.csv` with `entity_name`, `jurisdiction`, `is_usa`.

Normalize names before matching (upper, collapse `L.L.C.`/`L.P.`, strip Inc/Corp/LLC/LP/Company/Co/The).

## 3. Inventory current group

Direct children:

```sql
SELECT companyid, parentid, cs_company_id, company_name, company_type, company_country,
       deleted_by_editing_tool, deleted_by_import
FROM core_data.company_relationship
WHERE parentid = '<PARENT_COMPANYID>'
  AND deleted_by_editing_tool IS NULL
  AND deleted_by_import IS NULL
ORDER BY company_name;
```

Full tree (use `NOCYCLE` — relationship graphs can loop):

```sql
SELECT companyid, parentid, cs_company_id, company_name, company_type, LEVEL AS lvl
FROM core_data.company_relationship
WHERE deleted_by_editing_tool IS NULL
  AND deleted_by_import IS NULL
START WITH parentid = '<PARENT_COMPANYID>'
CONNECT BY NOCYCLE PRIOR companyid = parentid
       AND deleted_by_editing_tool IS NULL
       AND deleted_by_import IS NULL;
```

**Note:** `deleted_by_editing_tool` / `deleted_by_import` are date-ish — filter with `IS NULL`, not `NVL(...,'N')='N'` (avoids ORA-01858).

## 4. Cleanup removes (optional)

UI “Remove company (create subtree)” maps to:

`EDITING_API.PKG_ENTITY_GROUP.P_REMOVE_SUBTREE(i_companyid => …)`

`SET_COMPANY_RELATION` + `i_expiry_date` does **not** remove nodes (`company_relationship` has no expiry column).

Simple pack shape (preferred):

```sql
begin
  editing_api.pkg_entity_group.p_remove_subtree(i_companyid => 'PLC-...'); -- NAME
  -- commit;
  rollback;
end;
/
```

Before bulk remove: confirm candidates are **leaves** (0 active children). Prefer USA-only unless asked otherwise.

## 5. Gap classify (Oracle)

For each missing USA name after normalization:

1. `company_search_view` with `company_name LIKE 'PREFIX%'` (2-token prefix, then 1-token fallback). Keep searches narrow.
2. Prefer exact-norm **HQ** (`location_type = 1`).
3. Check `company_relationship` for that SAFE:
   - active non-BRANCH + `companyid` → **MOVE**
   - no non-BRANCH row → **ADD**
4. No exact HQ → **CREATE** (not endless REVIEW).
5. Exact BRANCH only → **REVIEW**.

Write gap workbook sheets: `move`, `add`, `create`, `review`, `already_in_group`.

## 6. Company Import (CREATE)

Template: `COMPANY_IMPORT_SAMPLE (5).xlsx` (or latest sample) — preserve sheets/`data` column order.

Populate **only**: COMPANY_NAME, ADDRESS, ADDRESS_TYPE, BUSINESS_TYPE, CITY, STATE, ZIP, LOCATION_TYPE.

| Field | Rule |
|-------|------|
| ADDRESS_TYPE | `S` street, `P` PO Box, `U` unclear |
| BUSINESS_TYPE | `L` LLC, `I` Inc, `C` Corp, `U` otherwise (incl. LP) |
| LOCATION_TYPE | `1` |
| ZIP | integer (match sample type) |
| ESTABLISH_DATE / extras | leave blank unless asked |

When source has no address (EX-21.1): using **UHC / SEC business address** is valid for creates.

Upload: `scripts/edit_tool_company_import_uploader.py` (needs approval).

## 7. Newly created → ADD candidates

After import:

```sql
SELECT cc.safe_number, cc.company_name, cc.address, cc.city, cc.state, cc.zip,
       cc.create_date AS import_date
FROM editing_api.company ec
INNER JOIN core_data.company cc ON cc.safe_number = ec.safe_number
WHERE ec.create_batch_id = -1
  AND ec.create_date > SYSDATE - 30
ORDER BY import_date DESC NULLS LAST, safe_number DESC;
```

Filter to today’s batch / expected address / CREATE name list. Those SAFEs become **ADD** (new creates have no companyid yet).

## 8. SQL packs (Biogen)

- **MOVE:** dual list `source_safe` + `target_uhc`; join non-BRANCH relationships; `PKG_ENTITY_GROUP.move_to_new_safe_number`. For soft-deleted history (ORA-20003 SAFEs), join source on `companyid is not null` **without** requiring `deleted_by_* IS NULL`.
- **ADD (US SAFE in Oracle):** **`PKG_ENTITY_RELATIONS.set_company_relation`** (not GROUP). Dual list child SAFE only; `i_companyid => null`, `i_company_name => null`, `i_company_country => 'UNITED STATES OF AMERICA'`, `i_expiry_date => add_months(sysdate, 1200)`, `i_is_hidden => 'N'`.
- **ADD (intl SAFE):** same package; dual list `child_safe`, `company_name`, `company_country`; pass **name + short country** (`CAN`/`IRL`/`NLD`/`MEX`/`FRA`/`GBR`/…). Non-US SAFEs often absent from `company_search_view` — still ADDable this way (Energy Transfer / BRIM pattern).
- **ADD (null SAFE / no report):** Edit Tool “Add company” with name + country only. Backend: `i_safe_number => null`, `i_company_name` + `i_company_country` as **full country label** (`BARBADOS`, `BAHAMAS`, `CANADA`, … — matches UI storage, not `BRB`). Creates `cs_company_id` null nodes under UHC (intentional for Connect NO_COVERAGE gaps; remove later via `p_remove_subtree` when a SAFE exists).
- GROUP.set_company_relation rebuilds full group structure and can orphan rows / fill tablespace — **never** for ADD.
- SQL comments: use ASCII `-` not em dashes (SQL Developer mojibake). Trailing `-- name` comments OK; no skip nests; prefer small batches; default `rollback` until <OPERATOR> flips to `commit`.

Templates: [reference.md](reference.md). Workbook generator: `scripts/group_structure_pack.py` (group-structure-pack skill).

## 9. Post-check

Re-query children under parentid / tree for added SAFEs; confirm `deleted_by_editing_tool` stamped on removes; update gap workbook `action_status`.

## Safety

- No backend execute without approval.
- Uncertain ownership narrative ≠ Oracle relationship evidence.
- Do not treat BRANCH as final group member without separation/HQ-swap review.
- Keep first-pass Oracle name searches simple (`LIKE 'PREFIX%'`).
