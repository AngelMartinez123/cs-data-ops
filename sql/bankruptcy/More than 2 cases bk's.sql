SELECT DISTINCT b.safe_number
FROM core_data.bankruptcy b
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND b.deleted_by_editing_tool IS NULL
  AND b.safe_number IS NOT NULL
GROUP BY b.safe_number
HAVING COUNT(DISTINCT b.unique_case_id) >= 2;


WITH safes AS (
  SELECT distinct b.safe_number
  FROM core_data.bankruptcy b
  WHERE b.defendant_type = 'B'
    AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
    AND b.deleted_by_editing_tool IS NULL
    AND b.safe_number IS NOT NULL
  GROUP BY b.safe_number
  HAVING COUNT(DISTINCT b.unique_case_id) >= 2
)
SELECT b.*
FROM core_data.bankruptcy b
JOIN safes s
  ON s.safe_number = b.safe_number
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND b.deleted_by_editing_tool IS NULL
ORDER BY b.safe_number, b.unique_case_id, b.filing_date DESC;


SELECT
    b.row_unique_id,
    COUNT(*) AS cnt
FROM core_data.bankruptcy b
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  and deleted_by_editing_tool is null -- reportable window
GROUP BY b.row_unique_id
HAVING COUNT(*) > 1
ORDER BY cnt DESC;

select *
from core_data.bankruptcy
where row_unique_id = '4217023242';


SELECT
    b.safe_number,
    COUNT(DISTINCT b.unique_case_id) AS distinct_case_cnt
FROM core_data.bankruptcy b
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND b.deleted_by_editing_tool IS NULL
  AND b.safe_number IS NOT NULL
GROUP BY b.safe_number
and filing_date => DATE '12-31-2025'
HAVING COUNT(DISTINCT b.unique_case_id) >= 2
ORDER BY distinct_case_cnt DESC, b.safe_number;


SELECT
    b.safe_number,
    COUNT(DISTINCT b.unique_case_id) AS distinct_case_cnt,
    EXTRACT(YEAR FROM MAX(b.filing_date)) AS latest_filing_year
FROM core_data.bankruptcy b
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND b.deleted_by_editing_tool IS NULL
  AND b.safe_number IS NOT NULL
GROUP BY b.safe_number
HAVING COUNT(DISTINCT b.unique_case_id) >= 2
ORDER BY
    latest_filing_year DESC,
    distinct_case_cnt DESC,
    b.safe_number;



SELECT
    b.safe_number,
    COUNT(DISTINCT b.unique_case_id) AS distinct_case_cnt,
    COUNT(DISTINCT b.defendant_name) AS distinct_defendant_name_cnt,
    MIN(b.filing_date) AS earliest_filing_date,
    MAX(b.filing_date) AS latest_filing_date
FROM core_data.bankruptcy b
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND b.deleted_by_editing_tool IS NULL
  AND b.safe_number IS NOT NULL
GROUP BY b.safe_number
HAVING COUNT(DISTINCT b.unique_case_id) >= 2
   AND COUNT(DISTINCT b.defendant_name) > 1
ORDER BY latest_filing_date DESC, distinct_case_cnt DESC, b.safe_number;



SELECT
    b.safe_number,
    COUNT(DISTINCT b.unique_case_id) AS distinct_case_cnt,
    COUNT(DISTINCT UPPER(TRIM(b.defendant_name))) AS distinct_defendant_name_cnt,
    MIN(b.filing_date) AS earliest_filing_date,
    MAX(b.filing_date) AS latest_filing_date
FROM core_data.bankruptcy b
WHERE b.defendant_type = 'B'
  AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND b.deleted_by_editing_tool IS NULL
  AND b.safe_number IS NOT NULL
GROUP BY b.safe_number
HAVING COUNT(DISTINCT b.unique_case_id) >= 2
   AND COUNT(DISTINCT UPPER(TRIM(b.defendant_name))) > 1
ORDER BY latest_filing_date DESC, distinct_case_cnt DESC, b.safe_number;


WITH bk AS (
  SELECT
      b.*,
      /* Normalize defendant name to reduce false differences */
      TRIM(
        REGEXP_REPLACE(
          REGEXP_REPLACE(
            REGEXP_REPLACE(
              UPPER(NVL(b.defendant_name, '')),
              '^[[:space:]]*THE[[:space:]]+', ''                -- optional: remove leading "THE "
            ),
            '[^A-Z0-9 ]', ' '                                   -- remove punctuation/symbols -> space
          ),
          '(^| )[ ]+', '\1'                                     -- collapse repeated spaces (simple pass)
        )
      ) AS def_name_norm_raw
  FROM core_data.bankruptcy b
  WHERE b.defendant_type = 'B'
    AND b.filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
    AND b.deleted_by_editing_tool IS NULL
    AND b.safe_number IS NOT NULL
),
bk2 AS (
  SELECT
      bk.*,
      /* Strip common business suffixes at the end (repeatable-ish) */
      TRIM(
        REGEXP_REPLACE(
          bk.def_name_norm_raw,
          '( (LLC|L L C|INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|LP|L P|LLP|L L P|LLLP|P C|PC|PLLC|P L L C))+$',
          ''
        )
      ) AS def_name_norm
  FROM bk bk
)
SELECT
    safe_number,
    COUNT(DISTINCT unique_case_id) AS distinct_case_cnt,
    COUNT(DISTINCT def_name_norm)  AS distinct_defendant_name_cnt,
    MIN(filing_date)               AS earliest_filing_date,
    MAX(filing_date)               AS latest_filing_date
FROM bk2
GROUP BY safe_number
HAVING COUNT(DISTINCT unique_case_id) >= 2
   AND COUNT(DISTINCT def_name_norm) > 1
ORDER BY latest_filing_date DESC, distinct_case_cnt DESC, safe_number;
