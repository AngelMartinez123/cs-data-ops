# Group Structure Examples

Walkthrough distilled from Example Holdings Inc. EX-21.1 cleanup (2026-07-30).

## Scenario

Rebuild / gap-fill subsidiaries under **Example Holdings Inc.** after scrubbing junk group nodes.

| Key | Value |
|-----|-------|
| UHC SAFE | `<SAFE_004>` |
| Parent companyid | `<COMPANY_ID>` |
| Source | SEC Exhibit 21.1 HTML (`Document.html`) |
| UHC address (creates) | `<SOURCE_ADDRESS>`, <CITY STATE ZIP> |

## What was done

1. **Inventory** active children under `<COMPANY_ID>`.
2. **REMOVE** USA nodes with null `cs_company_id` via simple `p_remove_subtree` list (many). Confirmed leaves first.
3. **REMOVE** USA nodes with `cs_company_id LIKE 'WY%'` (4 nodes).
4. **Parse EX-21.1** → the source list unique USA entities.
5. **Gap classify** vs Oracle tree:
   - Already in group by name: handful
   - MOVE: HQ + companyid
   - ADD: HQ, no group node
   - CREATE: no exact match after normalization (formerly “REVIEW”)
   - REVIEW: branch-only exact hits only
6. **Company Import** for CREATE rows using sample (5) + SEC address; ZIP as int; only 8 fields.
7. After <OPERATOR> imported: run `create_batch_id = -1` query → match new SAFEs (`<SAFE_005>`–`<SAFE_006>`).
8. **ADD pack** under `<SAFE_004>` — must use **`PKG_ENTITY_RELATIONS.set_company_relation`** with `i_expiry_date => add_months(sysdate, 1200)` and `i_is_hidden => 'N'`. Do **not** use `PKG_ENTITY_GROUP.set_company_relation` (full rebuild / tablespace / orphan rows).

## Lesson learned

| Topic | Rule |
|-------|------|
| **ADD package** | **`PKG_ENTITY_RELATIONS`**, not GROUP |
| ADD extras | `i_expiry_date => add_months(sysdate, 1200)`, `i_is_hidden => 'N'` |
| GROUP ADD failure mode | Rebuild fills `STAGING_LOAD_DATA`; orphans with null `companyid`/`parentid` |
| Orphan cleanup | Soft-delete UPDATE (procedures can't remove null-companyid orphans) |
| Remove | Use `p_remove_subtree`, not expiry on GROUP `SET_COMPANY_RELATION` |
| Delete filters | `deleted_* IS NULL` (dates, not `'N'`) |
| Tree walk | `CONNECT BY NOCYCLE` |
| No exact name | **CREATE**, not permanent REVIEW |
| Branch-only | Stay REVIEW |
| New creates | Always **ADD** via RELATIONS package |
| Intl SAFE ADD | Name + short country (`CAN`/`IRL`/…); SAFE may be absent from `company_search_view` |
| CLEAN ADD | Zero `company_relationship` rows; soft-deleted history → `ORA-20003` → **MOVE** |
| Null-SAFE ADD | `i_safe_number => null` + name + full country (`BARBADOS`) — Edit Tool “Add company” / Connect NO_COVERAGE |
| SQL comments | ASCII `-` only (em dashes break in SQL Developer) |
| Import format | Match latest `COMPANY_IMPORT_SAMPLE` sheets/headers/types exactly |

## Coworker replay (minimal prompts)

```text
/data-ops-preflight
Group structure for UHC US…. Source subsidiaries from this EX-21.1 HTML.
Inventory Oracle group, classify MOVE/ADD/CREATE/REVIEW, remove null SAFE USA if present,
build create import if needed, then ADD pack under the UHC after I import.
```

Or after creates already imported:

```text
Run the create_batch_id=-1 query, match to today's approved creates,
write ADD SQL under <SAFE_004> (rollback default).
```
