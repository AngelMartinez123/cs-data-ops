-- =============================================================================
-- Court ranking: TWO_CORE_RECORDS (active + released sibling, different case)
-- Use to prioritize bulk-import / matching rule fixes by court.
-- =============================================================================

with pairs as (
    select
        a.id as active_id,
        r.id as release_id,
        a.safe_number,
        a.jurisdiction_court_code as courtid,
        trim(upper(a.defendant_name)) as defendant_norm,
        a.amount,
        a.date_filed as active_date_filed,
        r.release_date,
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
court_open as (
    select
        jurisdiction_court_code as courtid,
        count(*) as total_open_liens
    from core_data.lien
    where release_date is null
      and deleted_by_import is null
      and deleted_by_editing_tool is null
    group by jurisdiction_court_code
)
select
    s.courtid,
    d.courtname,
    d.state,
    count(*) as candidate_pair_rows,
    count(distinct s.safe_number) as distinct_safes,
    count(distinct s.active_id) as distinct_active_liens,
    count(distinct case when s.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
                        then s.active_id end) as high_conf_1to1_active_liens,
    count(distinct case when s.match_confidence = 'MULTIPLE_POSSIBLE_MATCHES'
                        then s.active_id end) as ambiguous_active_liens,
    count(distinct s.defendant_norm) as distinct_defendants,
    co.total_open_liens,
    round(
        100 * count(distinct s.active_id) / nullif(co.total_open_liens, 0),
        2
    ) as pct_open_liens_with_duplicate_active,
    round(
        100 * count(distinct case when s.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
                                  then s.active_id end)
          / nullif(co.total_open_liens, 0),
        2
    ) as pct_open_1to1_duplicate_active,
    case
        when count(distinct case when s.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
                                 then s.active_id end) >= 5000
        then 'Y' else 'N'
    end as court_problem_flag
from scored s
left join source_legal_data.court_reference d
  on d.courtid = s.courtid
left join court_open co
  on co.courtid = s.courtid
group by s.courtid, d.courtname, d.state, co.total_open_liens
order by high_conf_1to1_active_liens desc nulls last;
