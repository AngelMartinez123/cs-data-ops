-- =============================================================================
-- Tax lien DELETE_ACTIVE_KEEP_RELEASE action pack
-- Problem: active tax lien still open while released sibling exists (diff case).
-- Remediation: DET import / ET delete on ACTIVE row only; keep RELEASE row.
-- No DML in this pack.
--
-- Working criteria (current):
--   * Tax open types: FT, ST, CT, TW
--   * Tax release types: FR, SR, CR, WR
--   * 1-to-1 pairing only (HIGH_CONFIDENCE_1_TO_1)
--   * release_date >= active date_filed
--   * Active filing within last 6 years 9 months (81 months)
--     -> excludes very old active rows; adjust ACTIVE_AGE filter below if needed
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1) Profile counts
-- -----------------------------------------------------------------------------
with pairs as (
    select
        a.id as active_id,
        r.id as release_id,
        a.safe_number,
        a.date_filed as active_date_filed,
        a.filing_type as active_filing_type,
        r.filing_type as release_filing_type
    from core_data.lien a
    join core_data.lien r
      on a.safe_number = r.safe_number
     and a.jurisdiction_court_code = r.jurisdiction_court_code
     and nvl(a.amount, -1) = nvl(r.amount, -1)
     and trim(upper(a.defendant_name)) = trim(upper(r.defendant_name))
    where a.release_date is null
      and a.deleted_by_import is null
      and a.deleted_by_editing_tool is null
      and r.release_date is not null
      and r.deleted_by_import is null
      and r.deleted_by_editing_tool is null
      and trim(a.case_number) <> trim(r.case_number)
      and r.release_date >= a.date_filed
      and a.filing_type in ('FT', 'ST', 'CT', 'TW')
      and r.filing_type in ('FR', 'SR', 'CR', 'WR')
),
scored as (
    select
        p.*,
        case
            when count(*) over (partition by active_id) = 1
             and count(*) over (partition by release_id) = 1
            then 'HIGH_CONFIDENCE_1_TO_1'
            else 'MULTIPLE_POSSIBLE_MATCHES'
        end as match_confidence
    from pairs p
)
select
    match_confidence,
    count(*) as pair_rows,
    count(distinct safe_number) as distinct_safes,
    count(distinct active_id) as distinct_active_liens
from scored
group by match_confidence
order by match_confidence;


-- -----------------------------------------------------------------------------
-- 2) Full 1-to-1 tax-lien review export (no age filter)
-- -----------------------------------------------------------------------------
with pairs as (
    select
        a.id as active_id,
        r.id as release_id,
        a.safe_number,
        a.jurisdiction_court_code as courtid,
        a.case_number as active_case_number,
        r.case_number as release_case_number,
        a.date_filed as active_date_filed,
        r.date_filed as release_date_filed,
        r.release_date,
        a.amount,
        a.defendant_name,
        a.defendant_address as active_address,
        r.defendant_address as release_address,
        a.filing_type as active_filing_type,
        r.filing_type as release_filing_type,
        a.filed_by as active_filed_by,
        r.filed_by as release_filed_by,
        a.other_case_number as active_other_case,
        r.other_case_number as release_other_case,
        a.row_unique_id as active_row_unique_id,
        r.row_unique_id as release_row_unique_id,
        case
            when a.filing_type = decode(r.filing_type, 'FR', 'FT', 'SR', 'ST', 'CR', 'CT', 'WR', 'TW')
            then 'Y' else 'N'
        end as exact_tax_pair_flag,
        case
            when trim(upper(nvl(a.defendant_address, ''))) = trim(upper(nvl(r.defendant_address, '')))
             and a.defendant_address is not null
            then 'Y' else 'N'
        end as address_match_flag
    from core_data.lien a
    join core_data.lien r
      on a.safe_number = r.safe_number
     and a.jurisdiction_court_code = r.jurisdiction_court_code
     and nvl(a.amount, -1) = nvl(r.amount, -1)
     and trim(upper(a.defendant_name)) = trim(upper(r.defendant_name))
    where a.release_date is null
      and a.deleted_by_import is null
      and a.deleted_by_editing_tool is null
      and r.release_date is not null
      and r.deleted_by_import is null
      and r.deleted_by_editing_tool is null
      and trim(a.case_number) <> trim(r.case_number)
      and r.release_date >= a.date_filed
      and a.filing_type in ('FT', 'ST', 'CT', 'TW')
      and r.filing_type in ('FR', 'SR', 'CR', 'WR')
),
scored as (
    select
        p.*,
        case
            when count(*) over (partition by active_id) = 1
             and count(*) over (partition by release_id) = 1
            then 'HIGH_CONFIDENCE_1_TO_1'
            else 'MULTIPLE_POSSIBLE_MATCHES'
        end as match_confidence
    from pairs p
)
select
    s.match_confidence,
    s.safe_number,
    vc.company_name,
    s.courtid,
    d.courtname,
    d.state as court_state,
    s.active_id as delete_candidate_lien_id,
    s.release_id as keep_release_lien_id,
    s.active_case_number,
    s.release_case_number,
    s.active_date_filed,
    s.release_date_filed,
    s.release_date,
    s.amount,
    s.defendant_name,
    s.active_address,
    s.release_address,
    s.active_filing_type,
    s.release_filing_type,
    s.exact_tax_pair_flag,
    s.address_match_flag,
    s.active_filed_by,
    s.release_filed_by,
    s.active_other_case,
    s.release_other_case,
    s.active_row_unique_id,
    s.release_row_unique_id,
    'DELETE_ACTIVE_KEEP_RELEASE' as proposed_action
from scored s
left join source_legal_data.court_reference d
  on d.courtid = s.courtid
left join company_search_view vc
  on vc.safe_number = s.safe_number
where s.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
order by
    s.courtid,
    s.safe_number,
    s.amount,
    s.active_date_filed desc;


-- -----------------------------------------------------------------------------
-- 3) ACTIONABLE export (current working criteria)
--    1-to-1 tax pairs + active filed within last 6y9m (81 months)
--    Use this for DET delete-import batching (3,000 rows/upload).
-- -----------------------------------------------------------------------------
with pairs as (
    select
        a.id as active_id,
        r.id as release_id,
        a.safe_number,
        a.jurisdiction_court_code as courtid,
        a.case_number as active_case_number,
        r.case_number as release_case_number,
        a.date_filed as active_date_filed,
        r.date_filed as release_date_filed,
        r.release_date,
        a.amount,
        a.defendant_name,
        a.defendant_address as active_address,
        r.defendant_address as release_address,
        a.filing_type as active_filing_type,
        r.filing_type as release_filing_type,
        a.filed_by as active_filed_by,
        r.filed_by as release_filed_by,
        a.other_case_number as active_other_case,
        r.other_case_number as release_other_case,
        a.row_unique_id as active_row_unique_id,
        r.row_unique_id as release_row_unique_id
    from core_data.lien a
    join core_data.lien r
      on a.safe_number = r.safe_number
     and a.jurisdiction_court_code = r.jurisdiction_court_code
     and nvl(a.amount, -1) = nvl(r.amount, -1)
     and trim(upper(a.defendant_name)) = trim(upper(r.defendant_name))
    where a.release_date is null
      and a.deleted_by_import is null
      and a.deleted_by_editing_tool is null
      and r.release_date is not null
      and r.deleted_by_import is null
      and r.deleted_by_editing_tool is null
      and trim(a.case_number) <> trim(r.case_number)
      and r.release_date >= a.date_filed
      and a.filing_type in ('FT', 'ST', 'CT', 'TW')
      and r.filing_type in ('FR', 'SR', 'CR', 'WR')
      and a.date_filed >= add_months(trunc(sysdate), -81)
),
scored as (
    select
        p.*,
        case
            when count(*) over (partition by active_id) = 1
             and count(*) over (partition by release_id) = 1
            then 'HIGH_CONFIDENCE_1_TO_1'
            else 'MULTIPLE_POSSIBLE_MATCHES'
        end as match_confidence
    from pairs p
)
select
    s.safe_number,
    vc.company_name,
    s.courtid,
    d.courtname,
    d.state as court_state,
    s.active_id as delete_candidate_lien_id,
    s.release_id as keep_release_lien_id,
    s.active_case_number,
    s.release_case_number,
    s.active_date_filed,
    s.release_date,
    s.amount,
    s.defendant_name,
    s.active_filing_type,
    s.release_filing_type,
    s.active_filed_by,
    s.active_other_case,
    s.release_other_case,
    s.active_row_unique_id,
    s.release_row_unique_id,
    'DELETE_ACTIVE_KEEP_RELEASE' as proposed_action
from scored s
left join source_legal_data.court_reference d
  on d.courtid = s.courtid
left join company_search_view vc
  on vc.safe_number = s.safe_number
where s.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
order by
    s.courtid,
    s.safe_number,
    s.amount,
    s.active_date_filed desc;


-- -----------------------------------------------------------------------------
-- 4) DET import-shaped rows for section 3 IDs (active lien only)
--    Columns match liens_sample template + delete flags = trunc(sysdate)
-- -----------------------------------------------------------------------------
with pairs as (
    select
        a.id as active_id,
        r.id as release_id,
        a.safe_number,
        a.date_filed as active_date_filed
    from core_data.lien a
    join core_data.lien r
      on a.safe_number = r.safe_number
     and a.jurisdiction_court_code = r.jurisdiction_court_code
     and nvl(a.amount, -1) = nvl(r.amount, -1)
     and trim(upper(a.defendant_name)) = trim(upper(r.defendant_name))
    where a.release_date is null
      and a.deleted_by_import is null
      and a.deleted_by_editing_tool is null
      and r.release_date is not null
      and r.deleted_by_import is null
      and r.deleted_by_editing_tool is null
      and trim(a.case_number) <> trim(r.case_number)
      and r.release_date >= a.date_filed
      and a.filing_type in ('FT', 'ST', 'CT', 'TW')
      and r.filing_type in ('FR', 'SR', 'CR', 'WR')
      and a.date_filed >= add_months(trunc(sysdate), -81)
),
scored as (
    select
        p.*,
        case
            when count(*) over (partition by active_id) = 1
             and count(*) over (partition by release_id) = 1
            then 'HIGH_CONFIDENCE_1_TO_1'
            else 'MULTIPLE_POSSIBLE_MATCHES'
        end as match_confidence
    from pairs p
),
action_ids as (
    select active_id
    from scored
    where match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
)
select
    coalesce(r.rmsid, l.row_unique_id) as rmsid,
    l.safe_number,
    l.date_filed,
    l.filing_type,
    l.amount,
    l.other_case_number,
    l.jurisdiction_court_code,
    l.case_number,
    l.action_type,
    l.filed_by,
    l.defendant_name,
    l.defendant_suffix,
    l.defendant_address,
    l.defendant_city,
    l.defendant_state,
    l.defendant_zip_code,
    l.release_date,
    trunc(sysdate) as deleted_by_import,
    trunc(sysdate) as deleted_by_editing_tool
from core_data.lien l
left join source_legal_data.lien_data_rollup r
  on r.id = l.id
where l.id in (select active_id from action_ids)
order by
    l.jurisdiction_court_code,
    l.safe_number,
    l.date_filed desc;
