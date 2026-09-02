-- =============================================================================
-- FINAL REVIEW QUERY (practical window)
-- Tax lien different-case release -> ORIGINAL_STILL_ACTIVE in CORE_DATA.LIEN
-- Window: filing/release date >= 2023-01-01
-- Scope: high-volume pattern courts from section 6 ranking
-- No DML.
-- =============================================================================

with pattern_courts as (
    select column_value as courtid
    from table(sys.odcivarchar2list(
        'IDADAC2','NYALBC1','GAFULD1','FLDADC1','FLPALC1','FLBROC1','FLCOUC1',
        'GAGWID1','FLHILC1','ALMOTC1','INMARD1','NMBERC1','OKOKLC1','MSHINC3',
        'GAHOUD1','GABIBD1','TXHAIC1','ORMARC1','NYORAC1','NYROCC1','NYERIC1',
        'TXDAAC1','GAFORD1','ALJEFC1','ORMULC1'
    ))
),
open_tax as (
    select
        s.courtid,
        trim(s.case_number) as case_number,
        trim(s.original_case) as original_case,
        trim(s.alternate_case) as alternate_case,
        trim(upper(s.defendant_name)) as defendant_norm,
        s.defendant_name,
        s.defedant_address as defendant_address,
        s.defendant_city,
        s.defendant_state,
        s.defendant_zip_code,
        s.amount,
        s.filing_date,
        s.filing_type,
        s.plaintiff,
        s.row_unique_id,
        s.rmsid,
        upper(regexp_replace(nvl(s.defedant_address, ''), '[^A-Z0-9]', '')) as addr_norm
    from source_legal_data.source_lien_judgment s
    join pattern_courts pc on pc.courtid = s.courtid
    where s.filing_type in ('FT','ST','CT','TW')
      and s.release_date is null
      and s.filing_date >= date '2023-01-01'
      and s.case_number is not null
      and s.amount is not null
      and s.defendant_name is not null
),
rel_tax as (
    select
        s.courtid,
        trim(s.case_number) as case_number,
        trim(s.original_case) as original_case,
        trim(s.alternate_case) as alternate_case,
        trim(upper(s.defendant_name)) as defendant_norm,
        s.defendant_name,
        s.defedant_address as defendant_address,
        s.defendant_city,
        s.defendant_state,
        s.defendant_zip_code,
        s.amount,
        s.filing_date,
        s.release_date,
        s.filing_type,
        s.plaintiff,
        s.row_unique_id,
        s.rmsid,
        upper(regexp_replace(nvl(s.defedant_address, ''), '[^A-Z0-9]', '')) as addr_norm
    from source_legal_data.source_lien_judgment s
    join pattern_courts pc on pc.courtid = s.courtid
    where s.filing_type in ('FR','SR','CR','WR')
      and s.release_date is not null
      and s.release_date >= date '2023-01-01'
      and s.case_number is not null
      and s.amount is not null
      and s.defendant_name is not null
),
cand as (
    select
        o.courtid,
        o.case_number as original_case_number,
        r.case_number as release_case_number,
        r.original_case as release_original_case_field,
        r.alternate_case as release_alternate_case,
        o.defendant_name as defendant,
        o.defendant_norm,
        o.amount,
        o.filing_date as original_filing_date,
        r.release_date,
        o.filing_type as original_filing_type,
        r.filing_type as release_filing_type,
        o.defendant_address as original_address,
        r.defendant_address as release_address,
        o.defendant_state as state,
        o.row_unique_id as original_source_id,
        r.row_unique_id as release_source_id,
        o.rmsid as original_rmsid,
        r.rmsid as release_rmsid,
        o.plaintiff as original_plaintiff,
        r.plaintiff as release_plaintiff,
        case
            when o.addr_norm is not null
             and o.addr_norm = r.addr_norm
             and length(o.addr_norm) > 0 then 'EXACT_ADDR'
            else 'ADDR_DIFF_OR_BLANK'
        end as address_signal,
        case
            when r.original_case is not null
             and r.original_case = o.case_number then 'Y'
            else 'N'
        end as original_case_link_flag
    from open_tax o
    join rel_tax r
      on r.courtid = o.courtid
     and r.defendant_norm = o.defendant_norm
     and r.amount = o.amount
     and r.case_number <> o.case_number
     and r.release_date >= o.filing_date
),
fp as (
    select
        courtid,
        defendant_norm,
        amount,
        count(distinct original_source_id) as open_cnt,
        count(distinct release_source_id) as release_cnt
    from cand
    group by courtid, defendant_norm, amount
),
classified as (
    select
        c.*,
        f.open_cnt,
        f.release_cnt,
        'HIGH_CONFIDENCE_1_TO_1' as match_confidence,
        f.open_cnt + f.release_cnt as ambiguity_count
    from cand c
    join fp f
      on f.courtid = c.courtid
     and f.defendant_norm = c.defendant_norm
     and f.amount = c.amount
    where f.open_cnt = 1
      and f.release_cnt = 1
),
core_o as (
    select
        jurisdiction_court_code as courtid,
        trim(case_number) as case_number,
        count(*) as core_cnt,
        max(safe_number) as safe_number,
        max(release_date) as release_date,
        max(case
                when release_date is null
                 and deleted_by_import is null
                 and deleted_by_editing_tool is null
                then id
            end) as active_id
    from core_data.lien
    where deleted_by_import is null
      and deleted_by_editing_tool is null
      and jurisdiction_court_code in (
          select courtid from pattern_courts
      )
    group by jurisdiction_court_code, trim(case_number)
),
core_r as (
    select
        jurisdiction_court_code as courtid,
        trim(case_number) as case_number,
        count(*) as core_cnt
    from core_data.lien
    where deleted_by_import is null
      and deleted_by_editing_tool is null
      and jurisdiction_court_code in (
          select courtid from pattern_courts
      )
    group by jurisdiction_court_code, trim(case_number)
),
joined as (
    select
        cl.*,
        d.courtname,
        d.state as court_state,
        nvl(co.core_cnt, 0) as core_orig_cnt,
        nvl(cr.core_cnt, 0) as core_rel_cnt,
        co.safe_number as core_safe_from_orig,
        co.release_date as core_release_date_on_orig,
        co.case_number as core_case_number,
        co.active_id as core_active_orig_id,
        ru.safe_number as rollup_safe
    from classified cl
    left join source_legal_data.court_reference d
      on d.courtid = cl.courtid
    left join core_o co
      on co.courtid = cl.courtid
     and co.case_number = cl.original_case_number
    left join core_r cr
      on cr.courtid = cl.courtid
     and cr.case_number = cl.release_case_number
    left join source_legal_data.lien_data_rollup ru
      on ru.rmsid = cl.original_rmsid
),
scored as (
    select
        j.*,
        case
            when j.core_orig_cnt > 1 or j.core_rel_cnt > 1 then 'AMBIGUOUS_CORE_MATCH'
            when j.core_orig_cnt = 1 and j.core_release_date_on_orig is not null then 'CORE_RELEASED_CORRECTLY'
            when j.core_orig_cnt = 1 and j.core_release_date_on_orig is null and j.core_rel_cnt = 1 then 'TWO_CORE_RECORDS'
            when j.core_orig_cnt = 1 and j.core_release_date_on_orig is null and j.core_rel_cnt = 0 then 'ORIGINAL_STILL_ACTIVE'
            when j.core_orig_cnt = 0 and j.core_rel_cnt = 1 then 'RELEASE_CASE_ONLY'
            when j.core_orig_cnt = 0 and j.core_rel_cnt = 0 then 'NO_CORE_MATCH'
            else 'AMBIGUOUS_CORE_MATCH'
        end as problem_type,
        case
            when j.original_case_link_flag = 'Y' then 'TIER0_ORIGINAL_CASE'
            when j.address_signal = 'EXACT_ADDR' then 'TIER1_NAME_AMT_ADDR'
            else 'TIER1_NAME_AMT'
        end as pair_tier,
        nvl(j.rollup_safe, j.core_safe_from_orig) as safe_number
    from joined j
)
select
    courtid,
    courtname,
    nvl(state, court_state) as state,
    defendant,
    amount,
    original_source_id,
    release_source_id,
    original_rmsid,
    release_rmsid,
    original_case_number,
    release_case_number,
    release_original_case_field as original_case,
    release_alternate_case as alternate_case,
    original_filing_date,
    release_date,
    original_address,
    release_address,
    original_filing_type,
    release_filing_type,
    original_plaintiff,
    release_plaintiff,
    address_signal,
    original_case_link_flag,
    pair_tier,
    safe_number,
    core_case_number,
    core_release_date_on_orig as core_release_date,
    core_active_orig_id,
    match_confidence,
    ambiguity_count,
    problem_type,
    'Y' as court_pattern_flag
from scored
where problem_type = 'ORIGINAL_STILL_ACTIVE'
order by courtid, defendant, amount;
