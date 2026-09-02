# Group Structure Reference

SQL and field details for [SKILL.md](SKILL.md).

## Core tables / packages

| Object | Use |
|--------|-----|
| `company_search_view` | Name/SAFE lookup (no schema prefix; synonym). Columns include `safe_number`, `company_name`, `location_type`, `address`, `city`, `state`, `zip` — **not** `companyid`. |
| `core_data.company_relationship` | Group nodes: `companyid`, `parentid`, `cs_company_id`, `company_name`, `company_type`, delete stamps |
| `core_data.company` | Company master / create_date |
| `editing_api.company` | Edit Tool create batch (`create_batch_id`, `create_date`) |
| `core_data.group_structure` | Flattened group presence checks |
| `reporting_utils.fn_companyid(safe)` | Resolve parent companyid for ADD |
| `reporting_utils.fn_br_count_for_hq(safe)` | Branch count (MOVE signal) |
| `PKG_ENTITY_GROUP.MOVE_TO_NEW_SAFE_NUMBER` | MOVE |
| `PKG_ENTITY_RELATIONS.SET_COMPANY_RELATION` | **ADD** subsidiary under UHC — US SAFE, intl SAFE (name+country), or null SAFE (`i_safe_number => null`); always `i_expiry_date => add_months(sysdate, 1200)`, `i_is_hidden => 'N'` |
| `PKG_ENTITY_GROUP.SET_COMPANY_RELATION` | **Do not use for ADD** — full `p_create_group_structure` rebuild (tablespace / orphan risk) |
| `PKG_ENTITY_GROUP.P_REMOVE_SUBTREE` | Soft-remove node (`DELETED_BY_EDITING_TOOL`) |

## Name normalization

```text
upper → & to AND → collapse L.L.C./L.P. → strip non [A-Z0-9]
→ remove tokens: INC CORPORATION CORP COMPANY CO LIMITED LTD LLC LP LLP PLC PC PA PLLC THE
→ collapse whitespace
```

Match on normalized equality for “exact”. LIKE prefixes use first 1–2 significant tokens + `%`.

## Pre-check pattern

```sql
SELECT
    reporting_utils.fn_br_count_for_hq(a.safe_number) AS cnt_br,
    CASE
        WHEN a.safe_number IN (
            SELECT safe_number FROM core_data.group_structure WHERE safe_number IS NOT NULL
        ) THEN 'Y' ELSE 'N'
    END AS sn_in_grpstr,
    a.*
FROM company_search_view a
WHERE a.safe_number IN ('US...', 'US...');
```

## MOVE pack (Biogen)

```sql
-- <uhc name> move to new group
set serveroutput on;

begin
    for r in (
        select distinct
               a.source_safe_number,
               a.target_uhc_safe_number,
               b.companyid as source_companyid,
               c.companyid as target_uhc_companyid
        from (
            select 'US_SOURCE' source_safe_number, 'US_UHC' target_uhc_safe_number from dual -- Name
            union all
            select 'US_SOURCE2', 'US_UHC' from dual -- Name2
        ) a
        inner join core_data.company_relationship b
            on a.source_safe_number = b.cs_company_id
           and b.deleted_by_editing_tool is null
           and b.deleted_by_import is null
           and b.company_type != 'BRANCH'
        inner join core_data.company_relationship c
            on a.target_uhc_safe_number = c.cs_company_id
           and c.deleted_by_editing_tool is null
           and c.deleted_by_import is null
           and c.company_type != 'BRANCH'
           and a.source_safe_number != a.target_uhc_safe_number
    ) loop
        begin
            editing_api.pkg_entity_group.move_to_new_safe_number(
                i_safe_number => r.target_uhc_safe_number,
                i_companyid   => r.source_companyid
            );
            dbms_output.put_line('MOVED ' || r.source_safe_number || ' -> ' || r.target_uhc_safe_number);
        exception
            when others then
                dbms_output.put_line('FAILED MOVE ' || r.source_safe_number || ' err=' || sqlerrm);
        end;
    end loop;
    -- commit;
    rollback;
end;
/
```

## ADD pack (Biogen / RELATIONS)

**Required:** `PKG_ENTITY_RELATIONS.set_company_relation` — not `PKG_ENTITY_GROUP` (GROUP rebuilds full group structure and can fill `STAGING_LOAD_DATA` / leave orphan `companyid`/`parentid` null rows).

```sql
-- add company under UHC
set serveroutput on;

declare
    l_parent_companyid varchar2(25);
    l_cur sys_refcursor;
begin
    l_parent_companyid := reporting_utils.fn_companyid('US_UHC');

    for r in (
        select 'US_CHILD' child_safe_number from dual -- Name
        union all
        select 'US_CHILD2' from dual -- Name2
    ) loop
        begin
            editing_api.pkg_entity_relations.set_company_relation(
                i_parentid        => l_parent_companyid,
                i_companyid       => null,
                i_safe_number     => r.child_safe_number,
                i_company_name    => null,
                i_company_type    => 'SUBSIDIARY',
                i_company_address => null,
                i_company_city    => null,
                i_company_state   => null,
                i_company_zipcode => null,
                i_company_phone   => null,
                i_company_country => 'UNITED STATES OF AMERICA',
                i_company_number  => null,
                i_expiry_date     => add_months(sysdate, 1200),
                i_dedupe_override => 'N',
                i_is_hidden       => 'N',
                o_cursor          => l_cur
            );
            if l_cur%isopen then close l_cur; end if;
            dbms_output.put_line('ADDED ' || r.child_safe_number || ' under US_UHC');
        exception
            when others then
                if l_cur%isopen then close l_cur; end if;
                dbms_output.put_line('FAILED ADD ' || r.child_safe_number || ' err=' || sqlerrm);
        end;
    end loop;
    -- commit;
    rollback;
end;
/
```

Prefer small batches. Successful ADDs create real `companyid` + `parentid` under the UHC.

## ADD pack — international SAFE (name + country)

Non-US Connect SAFEs (CA/IE/NL/MX/…) are often **not** in `company_search_view`. Still ADD via RELATIONS if **zero** `company_relationship` rows for that SAFE. Any history (including soft-deleted) → `ORA-20003` → use **MOVE** instead.

```sql
-- intl ADD under UHC (SAFE + name + short country)
set serveroutput on;
set define off;

declare
    l_parent_companyid varchar2(25);
    l_cur sys_refcursor;
begin
    l_parent_companyid := reporting_utils.fn_companyid('US_UHC');

    for r in (
        select '<SAFE_007>' child_safe_number, 'BRIM CONCRETE' company_name, 'CAN' company_country from dual union all
        select '<SAFE_008>' child_safe_number, 'SUNOCO IRELAND LIMITED' company_name, 'IRL' company_country from dual
    ) loop
        begin
            editing_api.pkg_entity_relations.set_company_relation(
                i_parentid        => l_parent_companyid,
                i_companyid       => null,
                i_safe_number     => r.child_safe_number,
                i_company_name    => r.company_name,
                i_company_type    => 'SUBSIDIARY',
                i_company_address => null,
                i_company_city    => null,
                i_company_state   => null,
                i_company_zipcode => null,
                i_company_phone   => null,
                i_company_country => r.company_country,
                i_company_number  => null,
                i_expiry_date     => add_months(sysdate, 1200),
                i_dedupe_override => 'N',
                i_is_hidden       => 'N',
                o_cursor          => l_cur
            );
            if l_cur%isopen then close l_cur; end if;
            dbms_output.put_line('ADDED ' || r.child_safe_number || ' under US_UHC');
        exception
            when others then
                if l_cur%isopen then close l_cur; end if;
                dbms_output.put_line('FAILED ADD ' || r.child_safe_number || ' err=' || sqlerrm);
        end;
    end loop;
    -- commit;
    rollback;
end;
/
```

Short country codes that work: `CAN`, `IRL`, `NLD`, `MEX`, `FRA`, `GBR` (and `UNITED STATES OF AMERICA` for US/PR SAFEs).

## ADD pack — null SAFE (Edit Tool “Add company” / no Connect report)

UI: company name + country dropdown only, blank SafeNumber → creates `cs_company_id` null subsidiary. Backend equivalent:

```sql
-- null-SAFE ADD (name + full country label; no SafeNumber)
set serveroutput on;
set define off;

declare
    l_parent_companyid varchar2(25);
    l_cur sys_refcursor;
begin
    l_parent_companyid := reporting_utils.fn_companyid('US_UHC');

    for r in (
        select 'Sol Petroleum Bahamas Limited (Bahamas)' company_name, 'BAHAMAS' company_country from dual
    ) loop
        begin
            editing_api.pkg_entity_relations.set_company_relation(
                i_parentid        => l_parent_companyid,
                i_companyid       => null,
                i_safe_number     => null,
                i_company_name    => r.company_name,
                i_company_type    => 'SUBSIDIARY',
                i_company_address => null,
                i_company_city    => null,
                i_company_state   => null,
                i_company_zipcode => null,
                i_company_phone   => null,
                i_company_country => r.company_country,
                i_company_number  => null,
                i_expiry_date     => add_months(sysdate, 1200),
                i_dedupe_override => 'N',
                i_is_hidden       => 'N',
                o_cursor          => l_cur
            );
            if l_cur%isopen then close l_cur; end if;
            dbms_output.put_line('ADDED (no SAFE) ' || r.company_name || ' / ' || r.company_country);
        exception
            when others then
                if l_cur%isopen then close l_cur; end if;
                dbms_output.put_line('FAILED ' || r.company_name || ' err=' || sqlerrm);
        end;
    end loop;
    -- commit;
    rollback;
end;
/
```

Use **full** country labels as stored (`BARBADOS`, `BAHAMAS`, `CANADA`, …) — UI shows `BRB - BARBADOS` but Oracle stores `BARBADOS`. These are the same null-SAFE nodes scrubbed for USA cleanup; fine for EX-21.1 Connect NO_COVERAGE gaps until a SAFE exists.

## MOVE note — soft-deleted history

If ADD fails with `ORA-20003` and a soft-deleted row still has `companyid`, MOVE with source join that allows deleted history:

```sql
inner join core_data.company_relationship b
    on a.source_safe_number = b.cs_company_id
   and b.company_type != 'BRANCH'
   and b.companyid is not null
-- do not require deleted_by_* IS NULL on source for this case
```

## REMOVE pack (`p_remove_subtree`)

```sql
-- remove null/bad SAFE nodes under parent
begin
  editing_api.pkg_entity_group.p_remove_subtree(i_companyid => 'PLC-...'); -- NAME
  editing_api.pkg_entity_group.p_remove_subtree(i_companyid => '<COMPANY_ID>'); -- REVIEWED NODE
  -- commit;
  rollback;
end;
/
```

Null SAFE discovery:

```sql
SELECT companyid, company_name, company_type, company_country, cs_company_id
FROM core_data.company_relationship
WHERE parentid = '<PARENT>'
  AND cs_company_id IS NULL
  AND company_country = 'UNITED STATES OF AMERICA'
  AND deleted_by_editing_tool IS NULL
  AND deleted_by_import IS NULL
ORDER BY company_name;
```

Bad prefix (example WY):

```sql
SELECT companyid, cs_company_id, company_name, company_type, company_country
FROM core_data.company_relationship
WHERE parentid = '<PARENT>'
  AND cs_company_id LIKE 'WY%'
  AND company_country = 'UNITED STATES OF AMERICA'
  AND deleted_by_editing_tool IS NULL
  AND deleted_by_import IS NULL
ORDER BY company_name;
```

Leaf check before remove:

```sql
SELECT COUNT(*) AS active_children
FROM core_data.company_relationship c
WHERE c.parentid IN ( /* candidate companyids */ )
  AND c.deleted_by_editing_tool IS NULL
  AND c.deleted_by_import IS NULL;
```

## Newly created companies query

```sql
SELECT cc.safe_number
      ,cc.company_name
      ,cc.address
      ,cc.city
      ,cc.state
      ,cc.zip
      ,cc.create_date AS import_date
FROM editing_api.company ec
INNER JOIN core_data.company cc
  ON (cc.safe_number = ec.safe_number)
WHERE ec.create_batch_id = -1
  AND ec.create_date > SYSDATE - 30
ORDER BY import_date DESC NULLS LAST, safe_number DESC;
```

New creates → ADD under UHC (not MOVE).

## Company Import columns (`data` sheet)

1-based indices used by team builders:

| Field | Col |
|-------|-----|
| COMPANY_NAME | 6 |
| ADDRESS | 7 |
| ADDRESS_TYPE | 8 |
| BUSINESS_TYPE | 14 |
| CITY | 33 |
| STATE | 34 |
| ZIP | 35 |
| LOCATION_TYPE | 44 |

Script: `scripts/edit_tool_company_import_uploader.py`
Oracle helper: `scripts/oracle_query.py`
Pack generator: `scripts/group_structure_pack.py`

## Edit Tool UI (when not using SQL)

Group page: `http://<EDIT_TOOL_HOST>/web/EditToolLive/GroupStructure/Index/<root_safe>`

- Add US company: fill `#input_safenumber`, `#add_company`, confirm dialog.
- Remove (create subtree) ↔ `p_remove_subtree`.

## Output file naming (suggested)

Under `work/YYYY-MM-DD/`:

| File | Contents |
|------|----------|
| `*_ex211_subsidiaries.csv` | Parsed subsidiary list |
| `*_group_current.csv` / `*_group_tree.csv` | Oracle inventory |
| `*_gap_review.xlsx` | move/add/create/review sheets |
| `*_remove_null_safe_usa.sql` | remove pack |
| `*_company_import_creates.xlsx` | import template filled |
| `*_created_safes.csv` | post-import SAFE map |
| `*_add_newly_created.sql` | ADD pack for creates |
| `*_move.sql` / `*_add.sql` | Biogen packs |
