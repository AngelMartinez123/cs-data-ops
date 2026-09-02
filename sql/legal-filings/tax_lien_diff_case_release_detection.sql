-- =============================================================================
-- Tax Lien Different-Case Release Detection (Oracle)
-- Source: LOAD_SOURCE_VENDOR_NEG.SOURCE_VENDOR_SLJ
-- Core:   CORE_DATA.LIEN
-- Purpose: Identify original/release pairs where the court used a different
--          case number on the release, then find Core liens still active.
-- NO DML against CORE_DATA.LIEN in this pack.
-- =============================================================================
-- Tax filing types (from DIC_SLJ_FILING_TYPES, GROUP_TYPE = Tax Lien):
--   Open / original : FT, ST, CT, TW  (+ renewals SZ, TZ optional)
--   Release         : FR, SR, CR, WR
-- Release indicator : RELEASE_DATE IS NOT NULL is primary;
--                     FILING_TYPE in (FR,SR,CR,WR) is confirmatory (R = release).
-- Address column on SLJ is misspelled: DEFEDANT_ADDRESS
-- Court names: LOAD_SOURCE_VENDOR_NEG.DIC_COURTS_SLJ_2015_05_13
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SECTION 1: Schema reminder / sample inventory
-- -----------------------------------------------------------------------------
/*
select column_name, data_type, column_id
from all_tab_columns
where owner = 'LOAD_SOURCE_VENDOR_NEG'
  and table_name = 'SOURCE_VENDOR_SLJ'
order by column_id;

select column_name, data_type, column_id
from all_tab_columns
where owner = 'CORE_DATA'
  and table_name = 'LIEN'
order by column_id;

select * from source_legal_data.filing_type_reference
where group_type = 'Tax Lien'
order by filing_type;
*/


-- -----------------------------------------------------------------------------
-- SECTION 2: Release representation profile
-- Confirms FT/ST/CT/TW ~= open, FR/SR/CR/WR ~= released
-- -----------------------------------------------------------------------------
select
    s.filing_type,
    d.filing_description,
    d.group_type,
    case when s.release_date is null then 'NULL_REL' else 'HAS_REL' end as rel_flag,
    count(*) as cnt
from source_legal_data.source_lien_judgment s
left join source_legal_data.filing_type_reference d
  on d.filing_type = s.filing_type
where s.filing_type in ('FT','FR','ST','SR','CT','CR','TW','WR','SZ','TZ')
group by
    s.filing_type,
    d.filing_description,
    d.group_type,
    case when s.release_date is null then 'NULL_REL' else 'HAS_REL' end
order by s.filing_type, rel_flag;


-- -----------------------------------------------------------------------------
-- SECTION 3: ORIGINAL_CASE / ALTERNATE_CASE linkage usefulness
-- Tier-0 = release.original_case = open.case_number (same court)
-- -----------------------------------------------------------------------------

-- 3a population of linkage fields on tax releases
select
    count(*) as tax_release_rows,
    sum(case when original_case is not null
              and trim(original_case) <> trim(case_number) then 1 else 0 end) as orig_case_diff_cnt,
    sum(case when alternate_case is not null
              and trim(alternate_case) <> trim(case_number) then 1 else 0 end) as alt_case_diff_cnt
from source_legal_data.source_lien_judgment
where filing_type in ('FR','SR','CR','WR')
  and release_date is not null;

-- 3b ORIGINAL_CASE hit-rate onto an open tax lien (same court)
with rel as (
    select
        courtid,
        case_number,
        original_case,
        alternate_case,
        defendant_name,
        amount,
        release_date,
        filing_type,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and original_case is not null
      and trim(original_case) <> trim(case_number)
)
select
    count(*) as releases_with_orig_case_diff,
    sum(case when o.row_unique_id is not null then 1 else 0 end) as matched_to_open,
    round(
        100 * sum(case when o.row_unique_id is not null then 1 else 0 end)
          / nullif(count(*), 0),
        2
    ) as pct_hit
from rel r
left join source_legal_data.source_lien_judgment o
  on o.courtid = r.courtid
 and trim(o.case_number) = trim(r.original_case)
 and o.filing_type in ('FT','ST','CT','TW')
 and o.release_date is null;

-- 3c ALTERNATE_CASE hit-rate onto an open tax lien (same court)
with rel as (
    select
        courtid,
        case_number,
        alternate_case,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and alternate_case is not null
      and trim(alternate_case) <> trim(case_number)
)
select
    count(*) as releases_with_alt_case_diff,
    sum(case when o.row_unique_id is not null then 1 else 0 end) as matched_to_open,
    round(
        100 * sum(case when o.row_unique_id is not null then 1 else 0 end)
          / nullif(count(*), 0),
        2
    ) as pct_hit
from rel r
left join source_legal_data.source_lien_judgment o
  on o.courtid = r.courtid
 and trim(o.case_number) = trim(r.alternate_case)
 and o.filing_type in ('FT','ST','CT','TW')
 and o.release_date is null;

-- 3d Tier-0 pairs via ORIGINAL_CASE (direct structural link)
select
    r.courtid,
    count(*) as paired_cnt
from source_legal_data.source_lien_judgment r
join source_legal_data.source_lien_judgment o
  on o.courtid = r.courtid
 and trim(o.case_number) = trim(r.original_case)
 and o.filing_type in ('FT','ST','CT','TW')
 and o.release_date is null
 and nvl(o.amount, -1) = nvl(r.amount, -1)
 and trim(upper(o.defendant_name)) = trim(upper(r.defendant_name))
where r.filing_type in ('FR','SR','CR','WR')
  and r.release_date is not null
  and r.original_case is not null
  and trim(r.case_number) <> trim(r.original_case)
group by r.courtid
order by paired_cnt desc;


-- -----------------------------------------------------------------------------
-- SECTION 4-5: High-confidence different-case pairs + ambiguity class
-- Fingerprint: COURTID + normalized defendant + amount
-- -----------------------------------------------------------------------------

with open_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(original_case) as original_case,
        trim(alternate_case) as alternate_case,
        trim(upper(defendant_name)) as defendant_norm,
        defendant_name,
        defedant_address as defendant_address,
        defendant_city,
        defendant_state,
        defendant_zip_code,
        amount,
        filing_date,
        release_date,
        filing_type,
        plaintiff,
        row_unique_id,
        rmsid
    from source_legal_data.source_lien_judgment
    where filing_type in ('FT','ST','CT','TW')
      and release_date is null
      and case_number is not null
      and amount is not null
      and defendant_name is not null
),
rel_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(original_case) as original_case,
        trim(alternate_case) as alternate_case,
        trim(upper(defendant_name)) as defendant_norm,
        defendant_name,
        defedant_address as defendant_address,
        defendant_city,
        defendant_state,
        defendant_zip_code,
        amount,
        filing_date,
        release_date,
        filing_type,
        plaintiff,
        row_unique_id,
        rmsid
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and case_number is not null
      and amount is not null
      and defendant_name is not null
),
cand as (
    select
        o.courtid,
        o.case_number as original_case_number,
        r.case_number as release_case_number,
        o.original_case as open_original_case,
        r.original_case as release_original_case,
        o.alternate_case as open_alternate_case,
        r.alternate_case as release_alternate_case,
        o.defendant_name,
        o.defendant_norm,
        o.amount,
        o.filing_date as original_filing_date,
        r.release_date,
        o.filing_type as original_filing_type,
        r.filing_type as release_filing_type,
        o.defendant_address as original_address,
        r.defendant_address as release_address,
        o.defendant_city as original_city,
        r.defendant_city as release_city,
        o.defendant_state as original_state,
        r.defendant_state as release_state,
        o.defendant_zip_code as original_zip,
        r.defendant_zip_code as release_zip,
        o.plaintiff as original_plaintiff,
        r.plaintiff as release_plaintiff,
        o.row_unique_id as original_source_id,
        r.row_unique_id as release_source_id,
        o.rmsid as original_rmsid,
        r.rmsid as release_rmsid,
        case
            when r.original_case is not null
             and trim(r.original_case) = trim(o.case_number)
            then 'Y' else 'N'
        end as original_case_link_flag,
        case
            when r.alternate_case is not null
             and trim(r.alternate_case) = trim(o.case_number)
            then 'Y' else 'N'
        end as alternate_case_link_flag
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
        case
            when f.open_cnt = 1 and f.release_cnt = 1 then 'HIGH_CONFIDENCE_1_TO_1'
            when f.open_cnt > 1 or f.release_cnt > 1 then 'MULTIPLE_POSSIBLE_MATCHES'
            else 'NO_CLEAR_PAIR'
        end as match_confidence,
        f.open_cnt + f.release_cnt as ambiguity_count
    from cand c
    join fp f
      on f.courtid = c.courtid
     and f.defendant_norm = c.defendant_norm
     and f.amount = c.amount
)
select *
from classified
where match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
  and rownum <= 500;   -- sample; remove rownum for full extract


-- -----------------------------------------------------------------------------
-- SECTION 6: Court ranking for different-case release behavior
-- -----------------------------------------------------------------------------

with open_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        filing_date,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where filing_type in ('FT','ST','CT','TW')
      and release_date is null
      and case_number is not null
      and amount is not null
      and defendant_name is not null
),
rel_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        release_date,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and case_number is not null
      and amount is not null
      and defendant_name is not null
),
cand as (
    select
        o.courtid,
        o.defendant_norm,
        o.amount,
        o.row_unique_id as original_source_id,
        r.row_unique_id as release_source_id
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
        c.courtid,
        c.defendant_norm,
        c.amount,
        c.original_source_id,
        c.release_source_id,
        case
            when f.open_cnt = 1 and f.release_cnt = 1 then 'HIGH_CONFIDENCE_1_TO_1'
            when f.open_cnt > 1 or f.release_cnt > 1 then 'MULTIPLE_POSSIBLE_MATCHES'
            else 'NO_CLEAR_PAIR'
        end as match_confidence
    from cand c
    join fp f
      on f.courtid = c.courtid
     and f.defendant_norm = c.defendant_norm
     and f.amount = c.amount
),
court_open as (
    select courtid, count(*) as tax_open_cnt
    from open_tax
    group by courtid
)
select
    cl.courtid,
    d.courtname,
    d.state,
    count(*) as candidate_pair_rows,
    count(distinct case when cl.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
                        then cl.original_source_id end) as high_conf_1to1_pairs,
    count(distinct case when cl.match_confidence = 'MULTIPLE_POSSIBLE_MATCHES'
                        then cl.original_source_id || ':' || cl.release_source_id end) as ambiguous_pair_rows,
    count(distinct cl.defendant_norm) as distinct_defendants,
    co.tax_open_cnt,
    round(
        100 * count(distinct case when cl.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
                                  then cl.original_source_id end)
          / nullif(co.tax_open_cnt, 0),
        2
    ) as pct_open_with_diff_case_1to1,
    case
        when count(distinct case when cl.match_confidence = 'HIGH_CONFIDENCE_1_TO_1'
                                 then cl.original_source_id end) >= 100
        then 'Y' else 'N'
    end as court_pattern_flag
from classified cl
left join source_legal_data.court_reference d
  on d.courtid = cl.courtid
left join court_open co
  on co.courtid = cl.courtid
group by cl.courtid, d.courtname, d.state, co.tax_open_cnt
order by high_conf_1to1_pairs desc nulls last;


-- -----------------------------------------------------------------------------
-- SECTION 7: Case-number behavior samples (top courts)
-- Look for containment / shared prefix; many courts use independent numbers
-- -----------------------------------------------------------------------------

with open_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        filing_date,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where filing_type in ('FT','ST','CT','TW')
      and release_date is null
      and amount is not null
),
rel_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        release_date,
        row_unique_id
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and amount is not null
),
pairs as (
    select
        o.courtid,
        o.case_number as original_case_number,
        r.case_number as release_case_number,
        o.defendant_norm,
        o.amount,
        case
            when instr(r.case_number, o.case_number) > 0 then 'REL_CONTAINS_ORIG'
            when instr(o.case_number, r.case_number) > 0 then 'ORIG_CONTAINS_REL'
            when substr(o.case_number, 1, 4) = substr(r.case_number, 1, 4)
             and length(o.case_number) > 4
             and length(r.case_number) > 4 then 'SHARED_PREFIX4'
            else 'INDEPENDENT'
        end as case_relation
    from open_tax o
    join rel_tax r
      on r.courtid = o.courtid
     and r.defendant_norm = o.defendant_norm
     and r.amount = o.amount
     and r.case_number <> o.case_number
     and r.release_date >= o.filing_date
)
select
    courtid,
    case_relation,
    count(*) as cnt
from pairs
group by courtid, case_relation
order by courtid, cnt desc;


-- -----------------------------------------------------------------------------
-- SECTION 8: Address confidence score (boost only; not a join key)
-- -----------------------------------------------------------------------------

with open_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        filing_date,
        row_unique_id,
        upper(regexp_replace(nvl(defedant_address, ''), '[^A-Z0-9]', '')) as addr_norm,
        upper(trim(defendant_city)) as city_norm,
        upper(trim(defendant_zip_code)) as zip_norm,
        upper(trim(plaintiff)) as plaintiff_norm
    from source_legal_data.source_lien_judgment
    where filing_type in ('FT','ST','CT','TW')
      and release_date is null
      and amount is not null
),
rel_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(upper(defendant_name)) as defendant_norm,
        amount,
        release_date,
        row_unique_id,
        upper(regexp_replace(nvl(defedant_address, ''), '[^A-Z0-9]', '')) as addr_norm,
        upper(trim(defendant_city)) as city_norm,
        upper(trim(defendant_zip_code)) as zip_norm,
        upper(trim(plaintiff)) as plaintiff_norm,
        trim(original_case) as original_case
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and amount is not null
),
cand as (
    select
        o.courtid,
        o.row_unique_id as original_source_id,
        r.row_unique_id as release_source_id,
        o.case_number as original_case_number,
        r.case_number as release_case_number,
        case
            when o.addr_norm is not null
             and o.addr_norm = r.addr_norm
             and length(o.addr_norm) > 0 then 'EXACT_ADDR'
            when o.zip_norm = r.zip_norm
             and o.city_norm = r.city_norm then 'CITY_ZIP'
            else 'ADDR_MISMATCH'
        end as address_signal,
        case
            when o.plaintiff_norm = r.plaintiff_norm
             and o.plaintiff_norm is not null then 'Y' else 'N'
        end as same_plaintiff,
        case
            when r.original_case is not null
             and r.original_case = o.case_number then 'Y' else 'N'
        end as original_case_link_flag
    from open_tax o
    join rel_tax r
      on r.courtid = o.courtid
     and r.defendant_norm = o.defendant_norm
     and r.amount = o.amount
     and r.case_number <> o.case_number
     and r.release_date >= o.filing_date
)
select
    address_signal,
    same_plaintiff,
    original_case_link_flag,
    count(*) as cnt
from cand
group by address_signal, same_plaintiff, original_case_link_flag
order by cnt desc;


-- -----------------------------------------------------------------------------
-- SECTION 9-10: Final review dataset with Core classification
-- Primary remediation population: PROBLEM_TYPE = ORIGINAL_STILL_ACTIVE
-- Active Core = RELEASE_DATE IS NULL AND DELETED_BY_IMPORT/EDITING_TOOL IS NULL
-- -----------------------------------------------------------------------------

with open_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(original_case) as original_case,
        trim(alternate_case) as alternate_case,
        trim(upper(defendant_name)) as defendant_norm,
        defendant_name,
        defedant_address as defendant_address,
        defendant_city,
        defendant_state,
        defendant_zip_code,
        amount,
        filing_date,
        filing_type,
        plaintiff,
        row_unique_id,
        rmsid,
        upper(regexp_replace(nvl(defedant_address, ''), '[^A-Z0-9]', '')) as addr_norm
    from source_legal_data.source_lien_judgment
    where filing_type in ('FT','ST','CT','TW')
      and release_date is null
      and case_number is not null
      and amount is not null
      and defendant_name is not null
),
rel_tax as (
    select
        courtid,
        trim(case_number) as case_number,
        trim(original_case) as original_case,
        trim(alternate_case) as alternate_case,
        trim(upper(defendant_name)) as defendant_norm,
        defendant_name,
        defedant_address as defendant_address,
        defendant_city,
        defendant_state,
        defendant_zip_code,
        amount,
        filing_date,
        release_date,
        filing_type,
        plaintiff,
        row_unique_id,
        rmsid,
        upper(regexp_replace(nvl(defedant_address, ''), '[^A-Z0-9]', '')) as addr_norm
    from source_legal_data.source_lien_judgment
    where filing_type in ('FR','SR','CR','WR')
      and release_date is not null
      and case_number is not null
      and amount is not null
      and defendant_name is not null
),
cand as (
    select
        o.courtid,
        o.case_number as original_case_number,
        r.case_number as release_case_number,
        o.original_case as open_original_case_field,
        r.original_case as release_original_case_field,
        o.alternate_case as open_alternate_case,
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
             and r.original_case = o.case_number then 'Y' else 'N'
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
        case
            when f.open_cnt = 1 and f.release_cnt = 1 then 'HIGH_CONFIDENCE_1_TO_1'
            when f.open_cnt > 1 or f.release_cnt > 1 then 'MULTIPLE_POSSIBLE_MATCHES'
            else 'NO_CLEAR_PAIR'
        end as match_confidence,
        f.open_cnt + f.release_cnt as ambiguity_count
    from cand c
    join fp f
      on f.courtid = c.courtid
     and f.defendant_norm = c.defendant_norm
     and f.amount = c.amount
    where f.open_cnt = 1
      and f.release_cnt = 1
),
core_hits as (
    select
        cl.*,
        d.courtname,
        d.state as court_state,
        -- Core match on original case
        (
            select count(*)
            from core_data.lien k
            where k.jurisdiction_court_code = cl.courtid
              and trim(k.case_number) = cl.original_case_number
              and k.deleted_by_import is null
              and k.deleted_by_editing_tool is null
        ) as core_orig_cnt,
        (
            select count(*)
            from core_data.lien k
            where k.jurisdiction_court_code = cl.courtid
              and trim(k.case_number) = cl.release_case_number
              and k.deleted_by_import is null
              and k.deleted_by_editing_tool is null
        ) as core_rel_cnt,
        (
            select max(k.safe_number)
            from core_data.lien k
            where k.jurisdiction_court_code = cl.courtid
              and trim(k.case_number) = cl.original_case_number
              and k.deleted_by_import is null
              and k.deleted_by_editing_tool is null
        ) as core_safe_from_orig,
        (
            select max(k.release_date)
            from core_data.lien k
            where k.jurisdiction_court_code = cl.courtid
              and trim(k.case_number) = cl.original_case_number
              and k.deleted_by_import is null
              and k.deleted_by_editing_tool is null
        ) as core_release_date_on_orig,
        (
            select max(k.case_number)
            from core_data.lien k
            where k.jurisdiction_court_code = cl.courtid
              and trim(k.case_number) = cl.original_case_number
              and k.deleted_by_import is null
              and k.deleted_by_editing_tool is null
        ) as core_case_number,
        (
            select max(k.id)
            from core_data.lien k
            where k.jurisdiction_court_code = cl.courtid
              and trim(k.case_number) = cl.original_case_number
              and k.release_date is null
              and k.deleted_by_import is null
              and k.deleted_by_editing_tool is null
        ) as core_active_orig_id
    from classified cl
    left join source_legal_data.court_reference d
      on d.courtid = cl.courtid
),
scored as (
    select
        h.*,
        case
            when h.core_orig_cnt > 1 or h.core_rel_cnt > 1 then 'AMBIGUOUS_CORE_MATCH'
            when h.core_orig_cnt = 1
             and h.core_release_date_on_orig is not null then 'CORE_RELEASED_CORRECTLY'
            when h.core_orig_cnt = 1
             and h.core_release_date_on_orig is null
             and h.core_rel_cnt = 1 then 'TWO_CORE_RECORDS'
            when h.core_orig_cnt = 1
             and h.core_release_date_on_orig is null
             and h.core_rel_cnt = 0 then 'ORIGINAL_STILL_ACTIVE'
            when h.core_orig_cnt = 0
             and h.core_rel_cnt = 1 then 'RELEASE_CASE_ONLY'
            when h.core_orig_cnt = 0
             and h.core_rel_cnt = 0 then 'NO_CORE_MATCH'
            else 'AMBIGUOUS_CORE_MATCH'
        end as problem_type,
        case
            when h.original_case_link_flag = 'Y' then 'TIER0_ORIGINAL_CASE'
            when h.address_signal = 'EXACT_ADDR' then 'TIER1_NAME_AMT_ADDR'
            else 'TIER1_NAME_AMT'
        end as pair_tier,
        nvl(ru.safe_number, h.core_safe_from_orig) as safe_number
    from core_hits h
    left join source_legal_data.lien_data_rollup ru
      on ru.rmsid = h.original_rmsid
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
    case when courtid in (
        -- populated after section 6 run; placeholder high-volume pattern courts
        select courtid from (
            select courtid from dual where 1 = 0
        )
    ) then 'Y' else 'REVIEW' end as court_pattern_flag
from scored
where problem_type = 'ORIGINAL_STILL_ACTIVE'
order by courtid, defendant, amount;


-- =============================================================================
-- OPTIONAL: Core-side different-case active/released pairs (<OPERATOR> seed pattern)
-- Useful as a Core-only sanity check; not a substitute for SLJ pairing.
-- =============================================================================
/*
select
    a.safe_number,
    a.defendant_name,
    a.jurisdiction_court_code,
    a.amount,
    a.case_number  as active_case_number,
    r.case_number  as released_case_number,
    a.date_filed   as active_date_filed,
    r.date_filed   as released_date_filed,
    r.release_date,
    a.filing_type  as active_filing_type,
    r.filing_type  as released_filing_type
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
order by a.jurisdiction_court_code, a.safe_number, a.amount;
*/
