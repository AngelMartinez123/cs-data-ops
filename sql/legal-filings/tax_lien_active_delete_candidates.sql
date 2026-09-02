-- =============================================================================
-- Tax lien active-delete candidates (1-to-1)
-- Problem: active tax lien (FT/ST/CT/TW) still open in Core while released
--          sibling (FR/SR/CR/WR) exists under a different case number.
-- Remediation: delete/hide ACTIVE row; keep RELEASE row on the report.
-- No DML.
-- =============================================================================

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
    s.active_date_filed desc
