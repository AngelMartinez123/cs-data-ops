---
name: group-structure-pack
description: Build group-structure action workbook and SQL bundle from candidate SAFE numbers and action types (move, add, branch_separate, review). Produces standard sheets, pre-check and post-check SQL. Use when <OPERATOR> asks for action xlsx, group structure pack, move/add SQL, branch promotion separation, or /group-structure-pack. For full research-to-pack workflow (EX-21.1 gaps, null SAFE remove, creates, newly created ADD), use entity-group-structure-workflow.
---

# Group Structure Pack

Generate the standard action package from an already-classified candidate list.

For end-to-end research (UHC inventory → gap classify MOVE/ADD/CREATE → remove null SAFE → Company Import → newly created ADD), use **[entity-group-structure-workflow](../entity-group-structure-workflow/SKILL.md)** first, then this pack (or hand-written Biogen SQL).

## Inputs required

- **Target UHC SAFE** (root/parent group)
- **Candidate list** with per-row:
  - `source_safe_number`
  - `action_type`: `move` | `add` | `branch_separate` | `review`
  - Optional: `company_id`, `company_name`, `confidence`, `evidence`, `caution_notes`

Use CSV format from `templates/group_structure_candidates.example.csv` in the workspace.

## Generate pack

```powershell
cd C:\Users\<USERNAME>\Projects\data-operations-workspace
python .\scripts\group_structure_pack.py `
  --input .\templates\group_structure_candidates.example.csv `
  --target-uhc <SAFE_009> `
  --output-dir .\work\2026-07-07
```

Replace the example CSV with <OPERATOR>'s real candidates before running.

## Outputs (under `work/YYYY-MM-DD/`)

1. **`group_structure_pack.xlsx`** with sheets:
   - `group_structure_review`
   - `oob_closed_action`
   - `move_to_new_group_sql`
   - `add_company_sql`
   - `review_not_actioned`

2. **`group_structure_pack_precheck.sql`** — branch count + `group_structure` presence for all SAFEs involved

3. **`group_structure_pack_postcheck.sql`** — same query to re-run after actions

## Action type mapping

| action_type | Backend path |
|-------------|--------------|
| `move` | `EDITING_API.PKG_ENTITY_GROUP.MOVE_TO_NEW_SAFE_NUMBER` |
| `add` | `EDITING_API.PKG_ENTITY_RELATIONS.SET_COMPANY_RELATION` (subsidiary; **not** GROUP) |
| `branch_separate` | Hide branch via `pkg_entity_relations.set_company_relation` + promotion block |
| `review` | No SQL — lands in `review_not_actioned` |

## Default SQL shape (required for <OPERATOR>)

Write runnable move/add SQL in the **Biogen pattern**. Do not overbuild with hardcoded company names, nested skip-if-exists logic, or long review essays inside the executable blocks.

### MOVE template

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
            select 'US...' source_safe_number, 'US...' target_uhc_safe_number from dual union all
            select 'US...', 'US...' from dual
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
    )
    loop
        begin
            editing_api.pkg_entity_group.move_to_new_safe_number(
                i_safe_number => r.target_uhc_safe_number,
                i_companyid   => r.source_companyid
            );
            dbms_output.put_line(
                'MOVED ' || r.source_safe_number ||
                ' companyid=' || r.source_companyid ||
                ' to target=' || r.target_uhc_safe_number
            );
        exception
            when others then
                dbms_output.put_line(
                    'FAILED MOVE ' || r.source_safe_number ||
                    ' err=' || sqlerrm
                );
        end;
    end loop;
    commit;
end;
/
```

### ADD template

**Required package:** `PKG_ENTITY_RELATIONS` — do **not** use `PKG_ENTITY_GROUP.set_company_relation` for ADD (full group rebuild / tablespace / orphan risk).

```sql
-- add company <uhc name>

set serveroutput on;

declare
    l_parent_companyid varchar2(25);
    l_cur sys_refcursor;
begin
    l_parent_companyid := reporting_utils.fn_companyid('US...');

    for r in (
        select 'US...' child_safe_number from dual union all
        select 'US...' from dual
    )
    loop
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
            dbms_output.put_line(
                'ADDED ' || r.child_safe_number ||
                ' under US...'
            );
            if l_cur%isopen then
                close l_cur;
            end if;
        exception
            when others then
                if l_cur%isopen then
                    close l_cur;
                end if;
                dbms_output.put_line(
                    'FAILED ADD ' || r.child_safe_number ||
                    ' err=' || sqlerrm
                );
        end;
    end loop;
    commit;
end;
/
```

Comments are encouraged for readability (e.g. `-- Capline Environmental Services LLC` on dual rows). For **US SAFE** ADDs keep `i_company_name => null` and SAFE-only dual lists. For **international SAFE** / **null-SAFE** ADDs, dual lists may include `company_name` + `company_country` (required). No nested skip logic. Put review/not-found notes in chat or short non-executable header comments only. Prefer ASCII `-` in comments (avoid em dashes — SQL Developer mojibake).

### ADD template — international SAFE

Non-US SAFE not in `company_search_view`: still ADD if **zero** relationship rows. Pass name + short country (`CAN`/`IRL`/`NLD`/`MEX`/`FRA`/`GBR`). Soft-deleted history → MOVE (`ORA-20003`), not ADD.

```sql
-- intl add company <uhc name>

set serveroutput on;
set define off;

declare
    l_parent_companyid varchar2(25);
    l_cur sys_refcursor;
begin
    l_parent_companyid := reporting_utils.fn_companyid('US...');

    for r in (
        select 'CA...' child_safe_number, 'COMPANY NAME' company_name, 'CAN' company_country from dual union all
        select 'IE...' child_safe_number, 'COMPANY NAME' company_name, 'IRL' company_country from dual
    )
    loop
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
            dbms_output.put_line('ADDED ' || r.child_safe_number || ' under US...');
            if l_cur%isopen then close l_cur; end if;
        exception
            when others then
                if l_cur%isopen then close l_cur; end if;
                dbms_output.put_line('FAILED ADD ' || r.child_safe_number || ' err=' || sqlerrm);
        end;
    end loop;
    commit;
end;
/
```

### ADD template — null SAFE (no Connect report)

Edit Tool “Add company” with name + country only. `i_safe_number => null`; country = **full label** (`BARBADOS`, not `BRB`).

```sql
-- null-SAFE add under <uhc>

set serveroutput on;
set define off;

declare
    l_parent_companyid varchar2(25);
    l_cur sys_refcursor;
begin
    l_parent_companyid := reporting_utils.fn_companyid('US...');

    for r in (
        select 'Entity Legal Name' company_name, 'BAHAMAS' company_country from dual
    )
    loop
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
            dbms_output.put_line('ADDED (no SAFE) ' || r.company_name || ' / ' || r.company_country);
            if l_cur%isopen then close l_cur; end if;
        exception
            when others then
                if l_cur%isopen then close l_cur; end if;
                dbms_output.put_line('FAILED ' || r.company_name || ' err=' || sqlerrm);
        end;
    end loop;
    commit;
end;
/
```

## Agent workflow

1. Run **data-ops-preflight** if Oracle access not yet verified.
2. Run pre-check SQL via `oracle_query.py` and fill `branch_count` / `sn_in_grpstr` in review sheet if missing.
3. Resolve `company_id` for `move` rows (`cnt_br > 0` means company ID required).
4. Present workbook + Biogen-shaped SQL to <OPERATOR> for approval before executing backend loops.
5. After approved actions, run post-check SQL and update `action_status` per row.

## Safety

- Do not execute backend PL/SQL without explicit approval.
- Uncertain roots / acquisition narratives → `review` only until Oracle `fn_companyid` evidence exists.
- Branch/HQ separation and HQ swap cases need extra caution notes.

Pair with `data-ops` and `entity-group-structure` rules for Edit Tool browser work when backend path is not appropriate.
