-- =============================================================================
-- SLJ validation pack for TWO_CORE_RECORDS Core pairs
-- Checks whether Lexis SLJ corroborates the active/release sibling relationship.
-- Separate from Core-only inventory; measures how much list shrinks with source proof.
-- =============================================================================

with pairs as (
    select
        a.id as active_id,
        r.id as release_id,
        a.safe_number,
        a.jurisdiction_court_code as courtid,
        trim(a.case_number) as active_case_number,
        trim(r.case_number) as release_case_number,
        a.date_filed as active_date_filed,
        r.release_date,
        a.amount,
        trim(upper(a.defendant_name)) as defendant_norm,
        a.filing_type as active_ft,
        r.filing_type as release_ft
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
slj_open as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        filing_date,
        filing_type,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where release_date is null
      and filing_type in ('FT','ST','CT','TW')
),
slj_rel as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(original_case) as original_case,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        release_date,
        filing_type,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where release_date is not null
      and filing_type in ('FR','SR','CR','WR')
),
validated as (
    select
        s.*,
        o.row_unique_id as slj_open_id,
        rel.row_unique_id as slj_release_id,
        case
            when o.row_unique_id is not null
             and rel.row_unique_id is not null
            then 'SLJ_BOTH_CASES'
            when rel.row_unique_id is not null
             and rel.original_case = s.active_case_number
            then 'SLJ_RELEASE_ORIGINAL_CASE_LINK'
            when o.row_unique_id is not null
             and rel.row_unique_id is null
            then 'SLJ_OPEN_ONLY'
            when o.row_unique_id is null
             and rel.row_unique_id is not null
            then 'SLJ_RELEASE_ONLY'
            else 'NO_SLJ_MATCH'
        end as slj_validation_status
    from scored s
    left join slj_open o
      on o.courtid = s.courtid
     and o.case_number = s.active_case_number
     and o.defendant_norm = s.defendant_norm
     and o.amount = s.amount
    left join slj_rel rel
      on rel.courtid = s.courtid
     and rel.case_number = s.release_case_number
     and rel.defendant_norm = s.defendant_norm
     and rel.amount = s.amount
     and rel.release_date >= s.active_date_filed
)
-- Shrinkage summary
select
    match_confidence,
    slj_validation_status,
    count(*) as pair_rows,
    count(distinct safe_number) as distinct_safes,
    count(distinct active_id) as distinct_active_liens
from validated
group by match_confidence, slj_validation_status
order by match_confidence, pair_rows desc;

-- Rollup: SLJ-proven vs not (for 1-to-1 tier)
/*
select
    match_confidence,
    case
        when slj_validation_status in ('SLJ_BOTH_CASES','SLJ_RELEASE_ORIGINAL_CASE_LINK')
        then 'SLJ_VALIDATED'
        else 'NOT_SLJ_VALIDATED'
    end as slj_proof_bucket,
    count(*) pair_rows,
    count(distinct safe_number) distinct_safes,
    count(distinct active_id) distinct_active_liens
from validated
group by match_confidence,
         case when slj_validation_status in ('SLJ_BOTH_CASES','SLJ_RELEASE_ORIGINAL_CASE_LINK')
              then 'SLJ_VALIDATED' else 'NOT_SLJ_VALIDATED' end
order by 1, 2;
*/
