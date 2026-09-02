select *
from source_legal_data.source_lien_judgment
where FILING_DATE < DATE '2026-01-01';

--raw source_vendor table

select count(*) --eliminate () for table view
from source_legal_data.source_bankruptcy
where defendant_type = 'B'
and filing_date <=  DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
  and courtid = 'KYEASF7';

--core bankruptcy

select COUNT(*) --eliminate () for table view
from CORE_DATA.BANKRUPTCY
where defendant_type = 'B'
and filing_date <=  DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
and courtid = 'KYEASF7';


select count(*)
from source_legal_data.source_bankruptcy
where defendant_type = 'B'
  and filing_date >= DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
  and courtid = 'KYEASF6';

select count(*)
from CORE_DATA.BANKRUPTCY
where defendant_type = 'B'
  and filing_date >= DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
  and courtid = 'KYEASF6';


select count(*)
from source_legal_data.source_bankruptcy
where defendant_type = 'B'
  and filing_date >= DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
  and courtid = 'KYEASF3';


select *
from CORE_DATA.BANKRUPTCY
where defendant_type = 'B'
and filing_date <  DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
and courtid = 'KYEASF7'
ORDER BY FILING_DATE DESC;

select *
from core_data.bankruptcy
where defendant_type = 'B'
  and filing_date <  DATE '2026-01-01'
  and filing_date >= add_months(trunc(sysdate), -117)
  and courtid = 'KYEASF7'
  and release_date is null
order by filing_date desc;


select *
from core_data.bankruptcy b
where b.defendant_type = 'B'
  and b.filing_date <  DATE '2026-01-01'
  and b.filing_date >= add_months(trunc(sysdate), -117)
  and b.courtid = 'KYEASF7'
  and not exists (
        select 1
        from core_data.bankruptcy x
        where x.courtid     = b.courtid
          and x.case_number = b.case_number
          and x.release_date is not null
  )
order by b.filing_date desc;


select * from core_data.bankruptcy
where case_number = '1670731TNW';


-- cases that may be active in kentucky courts

select *
from core_data.bankruptcy b
where b.defendant_type = 'B'
  and b.filing_date <=  DATE '2026-01-01'
  and b.filing_date >= add_months(trunc(sysdate), -117)
  and b.courtid = 'KYEASF7'
  and not exists (
        select 1
        from core_data.bankruptcy x
        where x.courtid     = b.courtid
          and x.case_number = b.case_number
          and x.release_date is not null
          and nvl(x.filing_types, '~') not in ('11TO','11C7','7TO','11CO','11TI')
  )
order by b.filing_date desc;

select * from core_data.bankruptcy
where other_case_number = '<ALTERNATE_CASE>';


select *
from core_data.bankruptcy b
where b.defendant_type = 'B'
  and trunc (b.filing_date) <= DATE '2026-01-01'
  and b.filing_date >= add_months(trunc(sysdate), -117)
  and b.courtid = 'KYEASF7'
  and not exists (
        select 1
        from core_data.bankruptcy x
        where x.courtid     = b.courtid
          and x.other_case_number = b.other_case_number
          and x.release_date is not null
          and nvl(x.filing_types, '~') not in ('11TO','11C7','7TO','11CO','11TI')
  )
order by b.filing_date desc;


select * from core_data.bankruptcy
where other_case_number = '<ALTERNATE_CASE>';


SELECT count(*)
FROM core_data.bankruptcy
WHERE defendant_type = 'B'
  AND filing_date >= ADD_MONTHS(TRUNC(SYSDATE), -117)
  AND deleted_by_editing_tool IS NULL;



select count(*)
from core_data.bankruptcy
where defendant_type = 'B'
  and filing_date >= add_months(trunc(sysdate), -117)
  and courtid = 'KYEASF7';
