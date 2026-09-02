CREATE OR REPLACE FORCE VIEW <USERNAME>.V_TO_BK_TEAM_TEMP_V3 AS
WITH u AS (
  SELECT
    /* base unmatched rows (same logic as V2) */
    REPORTING_UTILS.FN_SNSS_CHK(x.DEFENDANT_NAME, x.DEFENDANT_STATE) AS snss_chk,
    REPORTING_UTILS.FN_SOS_NAMESTATE_CHK(
      x.DEFENDANT_NAME,
      x.DEFENDANT_STREET_ADDRESS,
      x.DEFENDANT_CITY,
      x.DEFENDANT_STATE
    ) AS sos_snss,

    v.location_type AS hq_branch,
    x.courtid,
    x.other_case_number,
    x.filing_date,
    x.release_date,
    x.filing_types,
    x.original_chapter,
    d.filing_type_desc,

    x.dc_safe_number AS candidate_safe_number,
    x.defendant_name,
    v.company_name,
    x.defendant_street_address,
    v.address,
    x.defendant_city,
    v.city,
    x.defendant_state,
    v.state,
    x.defendant_zip_code,
    v.zip,

    CAST(NULL AS VARCHAR2(30)) AS rc_safe_number,
    CAST(NULL AS VARCHAR2(4000)) AS notes,

    x.rmsid,
    x.unique_case_id,
    x.create_batch_date,
    x.firstalgokey,

    /* extras you added in V2 */
    REPORTING_UTILS.FN_BR_COUNT_FOR_HQ(v.safe_number) AS cnt_br,
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM core_data.group_structure gs
        WHERE gs.safe_number = v.safe_number
          AND gs.safe_number IS NOT NULL
      ) THEN 'Y' ELSE 'N'
    END AS sn_in_grpstr,

    CASE
      WHEN v.safe_number IS NULL THEN NULL
      WHEN v.hq_safe_number IS NOT NULL THEN v.hq_safe_number
      ELSE v.safe_number
    END AS bk_target_safe_number,

    CASE
      WHEN v.safe_number IS NULL THEN 'NO_CANDIDATE_RECORD'
      WHEN v.hq_safe_number IS NOT NULL THEN 'CANDIDATE_IS_BRANCH_ROUTE_TO_HQ'
      ELSE 'CANDIDATE_IS_HQ'
    END AS bk_route_reason,

    /* standardized defendant name for grouping joins */
    LOAD.FN_SP_NEW_STRIP_PROC_NAME(x.defendant_name) AS def_spn,

    /* ZIP5 for consistent keying */
    SUBSTR(x.defendant_zip_code, 1, 5) AS def_zip5

  FROM STAGING_DATA.UNMATCHED_BANKRUPTCY x
  INNER JOIN core_data.dic_filing_types d
    ON TRIM(x.filing_types) = TRIM(d.filing_type)
  LEFT JOIN <USERNAME>.V_COMPANY_SEARCH_1R v
    ON v.safe_number = x.dc_safe_number
  WHERE NOT EXISTS (
    SELECT 1
    FROM core_data.bankruptcy b
    WHERE b.courtid = x.courtid
      AND b.other_case_number = x.other_case_number
      AND b.filing_types = x.filing_types
  )
),
addr_procd AS (
  /* Standardize addresses using Ethan�s package; RMSID is the SRC_RID */
  SELECT
    p.src_rid,
    p.addr_prim_addr_num,
    p.addr_street_name_stdz,
    p.exception_flag
  FROM TABLE(
    LOAD.ADDR_PROC_PKG.ADDR_PROC_FN(
      Q'[
        (
          SELECT
            rmsid AS src_rid,
            defendant_street_address
          FROM STAGING_DATA.UNMATCHED_BANKRUPTCY
          WHERE rmsid IS NOT NULL
        )
      ]',
      'SRC_RID',
      'DEFENDANT_STREET_ADDRESS'
    )
  ) p
),
u2 AS (
  /* join standardized address parts back to the u rows */
  SELECT
    u.*,
    ap.addr_prim_addr_num,
    ap.addr_street_name_stdz,
    ap.exception_flag,

    /* Build the exact HORIZ short key format:
       num!street_name!state!zip5 */
    ap.addr_prim_addr_num
      || '!' || ap.addr_street_name_stdz
      || '!' || u.defendant_state
      || '!' || u.def_zip5 AS def_addr_short_key
  FROM u
  LEFT JOIN addr_procd ap
    ON ap.src_rid = u.rmsid
),
cand_exact AS (
  /* Tier 0: exact standardized address match */
  SELECT
    u2.courtid,
    u2.other_case_number,
    u2.filing_types,
    h.safe_number AS addr_cand_safe_number,
    h.addr_short_key AS addr_short_key_hit,
    0 AS tier,
    'EXACT_SHORT_KEY' AS addr_match_reason,
    h.count_sns_at_short_addr,
    h.count_sns_at_full_addr,
    h.count_spname_sns,
    h.last_modified_date
  FROM u2
  JOIN GROUPING_DATA.GROUPING_KEYS_HORIZ_ADDR h
    ON h.strip_proc_name = u2.def_spn
   AND h.addr_short_key  = u2.def_addr_short_key
),
cand_fallback AS (
  /* Tier 1: your required fallback = same name + same state
     Only used when Tier 0 produced no candidates for the case */
  SELECT
    u2.courtid,
    u2.other_case_number,
    u2.filing_types,
    h.safe_number AS addr_cand_safe_number,
    h.addr_short_key AS addr_short_key_hit,
    1 AS tier,
    'NAME+STATE_FALLBACK' AS addr_match_reason,
    h.count_sns_at_short_addr,
    h.count_sns_at_full_addr,
    h.count_spname_sns,
    h.last_modified_date
  FROM u2
  JOIN GROUPING_DATA.GROUPING_KEYS_HORIZ_ADDR h
    ON h.strip_proc_name = u2.def_spn
   AND h.state          = u2.defendant_state
  WHERE NOT EXISTS (
    SELECT 1
    FROM cand_exact e
    WHERE e.courtid = u2.courtid
      AND e.other_case_number = u2.other_case_number
      AND e.filing_types = u2.filing_types
  )
),
cand_all AS (
  SELECT * FROM cand_exact
  UNION ALL
  SELECT * FROM cand_fallback
),
best_addr AS (
  SELECT *
  FROM (
    SELECT
      c.*,
      ROW_NUMBER() OVER (
        PARTITION BY c.courtid, c.other_case_number, c.filing_types
        ORDER BY
          c.tier,
          /* prefer less ambiguous */
          NVL(c.count_sns_at_full_addr,  999999),
          NVL(c.count_sns_at_short_addr, 999999),
          NVL(c.count_spname_sns,        999999),
          /* prefer most recently modified */
          c.last_modified_date DESC,
          /* deterministic */
          c.addr_cand_safe_number
      ) rn
    FROM cand_all c
  )
  WHERE rn = 1
),
addr_route AS (
  SELECT
    ba.*,
    vc.location_type AS addr_cand_loc_type,
    vc.hq_safe_number AS addr_cand_hq_safe,
    vc.hq_name AS addr_cand_hq_name,
    CASE
      WHEN vc.safe_number IS NULL THEN NULL
      WHEN vc.hq_safe_number IS NOT NULL THEN vc.hq_safe_number
      ELSE vc.safe_number
    END AS addr_bk_target_safe_number,
    CASE
      WHEN vc.safe_number IS NULL THEN 'NO_DB_RECORD_FOR_ADDR_CAND'
      WHEN vc.hq_safe_number IS NOT NULL THEN 'ADDR_CAND_IS_BRANCH_ROUTE_TO_HQ'
      ELSE 'ADDR_CAND_IS_HQ'
    END AS addr_bk_route_reason
  FROM best_addr ba
  LEFT JOIN <USERNAME>.V_COMPANY_SEARCH_1R vc
    ON vc.safe_number = ba.addr_cand_safe_number
)
SELECT
  CASE WHEN u2.snss_chk = u2.candidate_safe_number THEN 1 ELSE 0 END AS high_conf,
  u2.*,

  /* standardized address debug columns */
  u2.addr_prim_addr_num,
  u2.addr_street_name_stdz,
  u2.exception_flag,
  u2.def_addr_short_key,

  /* address candidate */
  ar.addr_cand_safe_number,
  ar.addr_match_reason,
  ar.addr_short_key_hit,
  ar.count_sns_at_full_addr  AS addr_cnt_full,
  ar.count_sns_at_short_addr AS addr_cnt_short,
  ar.count_spname_sns        AS addr_cnt_spn_sns,
  ar.last_modified_date      AS addr_last_mod_dt,

  /* routing for address candidate */
  ar.addr_cand_loc_type,
  ar.addr_cand_hq_safe,
  ar.addr_cand_hq_name,
  ar.addr_bk_target_safe_number,
  ar.addr_bk_route_reason
FROM u2
LEFT JOIN addr_route ar
  ON ar.courtid = u2.courtid
 AND ar.other_case_number = u2.other_case_number
 AND ar.filing_types = u2.filing_types;




SELECT *
FROM TABLE(
  LOAD.ADDR_PROC_PKG.ADDR_PROC_FN(
    Q'[(select rmsid as src_rid, defendant_street_address
        from STAGING_DATA.UNMATCHED_BANKRUPTCY
        where rmsid is not null and rownum <= 50)]',
    'SRC_RID',
    'DEFENDANT_STREET_ADDRESS'
  )
)
WHERE rownum <= 50;



SHOW ERRORS VIEW <USERNAME>.V_TO_BK_TEAM_TEMP_V3;





set sqlformat csv
spool "C:/Users/<USERNAME>/OneDrive - Data Operations/bk_output_operator_test/bk_test_FEB19.CSV"

set sqlformat csv;

spool "C:/Users/<USERNAME>/OneDrive - Data Operations/bk_output_operator_test/bk_test_FEB20.CSV";

WITH u AS (
  SELECT *
  FROM <USERNAME>.V_TO_BK_TEAM_TEMP_V2
  WHERE rmsid IS NOT NULL
),
addr_procd AS (
  /* NOTE: SRC_RID comes back as SAFE_NUMBER from the table function */
  SELECT
    p.safe_number AS rmsid,
    p.addr_prim_addr_num,
    p.addr_street_name_stdz,
    p.exception_flag
  FROM TABLE(
    LOAD.ADDR_PROC_PKG.ADDR_PROC_FN(
      Q'[
        (
          SELECT
            rmsid AS src_rid,
            defendant_street_address
          FROM STAGING_DATA.UNMATCHED_BANKRUPTCY
          WHERE rmsid IS NOT NULL
        )
      ]',
      'SRC_RID',
      'DEFENDANT_STREET_ADDRESS'
    )
  ) p
),
u2 AS (
  SELECT
    u.*,
    ap.addr_prim_addr_num,
    ap.addr_street_name_stdz,
    ap.exception_flag,
    LOAD.FN_SP_NEW_STRIP_PROC_NAME(u.defendant_name) AS def_spn,
    SUBSTR(u.defendant_zip_code, 1, 5) AS def_zip5,
    /* build the same short key style as HORIZ */
    ap.addr_prim_addr_num
      || '!' || ap.addr_street_name_stdz
      || '!' || u.defendant_state
      || '!' || SUBSTR(u.defendant_zip_code, 1, 5) AS def_addr_short_key
  FROM u
  LEFT JOIN addr_procd ap
    ON ap.rmsid = u.rmsid
),
cand AS (
  SELECT
    u2.courtid,
    u2.other_case_number,
    u2.filing_types,

    h.safe_number AS addr_cand_safe_number,
    h.addr_short_key AS addr_short_key_hit,

    CASE
      WHEN h.addr_short_key = u2.def_addr_short_key THEN 'EXACT_SHORT_KEY'
      ELSE 'NAME+STATE_FALLBACK'
    END AS addr_match_reason,

    ROW_NUMBER() OVER (
      PARTITION BY u2.courtid, u2.other_case_number, u2.filing_types
      ORDER BY
        /* exact addr key first */
        CASE WHEN h.addr_short_key = u2.def_addr_short_key THEN 0 ELSE 1 END,

        /* prefer less ambiguous */
        NVL(h.count_sns_at_full_addr,  999999),
        NVL(h.count_sns_at_short_addr, 999999),
        NVL(h.count_spname_sns,        999999),

        /* prefer most recently modified */
        h.last_modified_date DESC,

        /* deterministic */
        h.safe_number
    ) rn
  FROM u2
  JOIN GROUPING_DATA.GROUPING_KEYS_HORIZ_ADDR h
    ON h.strip_proc_name = u2.def_spn
   AND h.state          = u2.defendant_state
)
SELECT
  u2.*,
  c.addr_cand_safe_number,
  c.addr_match_reason,
  c.addr_short_key_hit
FROM u2
LEFT JOIN (SELECT * FROM cand WHERE rn = 1) c
  ON c.courtid = u2.courtid
 AND c.other_case_number = u2.other_case_number
 AND c.filing_types = u2.filing_types
;

spool off;







set sqlformat csv;
spool "C:/Users/<USERNAME>/OneDrive - Data Operations/bk_output_operator_test/bk_test_FEB19.CSV"
select *
from <USERNAME>.V_TO_BK_TEAM_TEMP_V3;
spool off;
