import csv
import json
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError


EASTERN = ZoneInfo("America/New_York")
REGION = "eu-west-1"
ATHENA_CATALOG = "AwsDataCatalog"
ATHENA_DATABASE = "<ATHENA_DATABASE>"
ATHENA_WORKGROUP = "<ATHENA_WORKGROUP>"
S3_UNMATCHED_PREFIX = "s3://<S3_BUCKET>/<USER_PREFIX>/unmatched/"
S3_FileTransfer_INPUT_PREFIX = "s3://<S3_BUCKET>/<USER_PREFIX>/file_transfer_input/"
S3_AUTO_MATCH_PREFIX = "s3://<S3_BUCKET>/<USER_PREFIX>/auto_matches/"
CRAWLER_NAME = "bankruptcy_verification_crawler"
VERIFIED_TABLE = "verified_bankruptcy_matches"
READINESS_MAX_ATTEMPTS = 15
READINESS_SLEEP_SECONDS = 60


UNMATCHED_SQL = """
WITH base AS (
    SELECT
        *,
        substr(entity_type, 1, 1) AS defendant_type
    FROM source_bankruptcy_raw
    WHERE dt = '{yyyymmdd}'
),
valid_cases AS (
    SELECT
        cust_court,
        case_number
    FROM base
    GROUP BY cust_court, case_number
    HAVING SUM(CASE WHEN defendant_type = 'B' THEN 1 ELSE 0 END) > 0
),
raw AS (
    SELECT b.*
    FROM base b
    JOIN valid_cases v
        ON b.cust_court = v.cust_court
        AND b.case_number = v.case_number
),
verified AS (
    SELECT
        list_of_unique_ids,
        filter(list_of_unique_ids, x -> x LIKE 'US%') AS safe_number_list
    FROM verified_bankruptcy_matches
    WHERE dt = '{yyyymmdd}'
)
SELECT
    r.*,
    b.list_of_unique_ids,
    b.safe_number_list
FROM raw r
JOIN verified b
    ON contains(b.list_of_unique_ids, r.unique_id)
WHERE cardinality(b.safe_number_list) <> 1
""".strip()


FileTransfer_INPUT_SQL = """
WITH base AS (
    SELECT
        *,
        substr(entity_type, 1, 1) AS defendant_type
    FROM source_bankruptcy_raw
    WHERE dt = '{yyyymmdd}'
),
valid_cases AS (
    SELECT
        cust_court,
        case_number
    FROM base
    GROUP BY cust_court, case_number
    HAVING SUM(CASE WHEN defendant_type = 'B' THEN 1 ELSE 0 END) > 0
),
raw AS (
    SELECT b.*
    FROM base b
    JOIN valid_cases v
        ON b.cust_court = v.cust_court
        AND b.case_number = v.case_number
),
verified AS (
    SELECT
        list_of_unique_ids,
        filter(list_of_unique_ids, x -> x LIKE 'US%') AS safe_number_list
    FROM verified_bankruptcy_matches
    WHERE dt = '{yyyymmdd}'
),
cte AS (
    SELECT
        r.*,
        b.list_of_unique_ids,
        b.safe_number_list
    FROM raw r
    JOIN verified b
        ON contains(b.list_of_unique_ids, r.unique_id)
    WHERE cardinality(b.safe_number_list) <> 1
)
SELECT
    '' AS cs_company_id,
    'US' AS country_code,
    '' AS org_number,
    '' AS company_number,
    '' AS vat_number,
    '' AS reg_number,
    '' AS tax_id,
    r.defendant_name AS name,
    '' AS trading_name,
    '' AS alias_name,
    '' AS previous_name1,
    '' AS previous_name2,
    r.unique_id AS reference,
    '' AS phone,
    '' AS email,
    r.defendant_address AS address1,
    '' AS address2,
    '' AS address3,
    r.defendant_city AS town,
    '' AS address5,
    r.defendant_state AS region,
    '' AS web_address,
    r.defendant_zip_code AS zip,
    '' AS portfolio_id,
    '' AS portlet_id,
    '' AS graydon_id,
    '' AS connect_id,
    '' AS ggs_id,
    '' AS alternate_os_path
FROM cte r
""".strip()


AUTO_MATCH_SQL = """
WITH base AS (
    SELECT
        b.*,
        substr(entity_type, 1, 1) AS defendant_type
    FROM source_bankruptcy_raw b
    WHERE dt = '{yyyymmdd}'
      AND delete_flag IS NULL
),
valid_cases AS (
    SELECT
        cust_court AS courtid,
        case_number
    FROM base
    GROUP BY cust_court, case_number
    HAVING SUM(CASE WHEN defendant_type = 'B' THEN 1 ELSE 0 END) > 0
),
base1 AS (
    SELECT b.*
    FROM base b
    JOIN valid_cases v
      ON b.cust_court = v.courtid
     AND b.case_number = v.case_number
),
b_expanded AS (
    SELECT
        v.list_of_unique_ids,
        uid
    FROM verified_bankruptcy_matches v
    CROSS JOIN UNNEST(v.list_of_unique_ids) AS t(uid)
    WHERE v.dt = '{yyyymmdd}'
),
cte AS (
    SELECT
        b.*,
        filter(v.list_of_unique_ids, x -> x LIKE 'US%') AS safe_number_list
    FROM base1 b
    JOIN b_expanded v
      ON b.unique_id = v.uid
    WHERE cardinality(filter(v.list_of_unique_ids, x -> x LIKE 'US%')) = 1
)
SELECT
    c.location_type,
    b.cust_court,
    b.alternate_case AS alternate_case_number,
    b.filing_date,
    b.release_date,
    b.cust_file_type AS filing_type,
    b.original_chapter AS original_filing_type,
    regexp_replace(
        array_join(safe_number_list, ','),
        '\\[|\\]',
        ''
    ) AS safe_number,
    b.defendant_name,
    c.company_name,
    b.defendant_address,
    c.address AS company_address,
    b.defendant_city,
    c.city AS company_city,
    b.defendant_state,
    c.state AS company_state,
    b.defendant_zip_code AS defendant_zip,
    c.zip AS company_zip,
    b.rmsid AS defendant_rmsid,
    b.unique_case_id,
    b.unique_id
FROM cte b
LEFT JOIN source_company_index c
  ON regexp_replace(array_join(safe_number_list, ','), '\\[|\\]', '') = c.safe_number
 AND c.dt = (
     SELECT MAX(dt)
     FROM source_company_index
 )
 AND c.deleted_by_editing_tool IS NULL
 AND c.deleted_by_import IS NULL
ORDER BY
    b.cust_court,
    b.filing_date
""".strip()


def arg_value(name, default=None):
    prefix = f"--{name}="
    for index, arg in enumerate(sys.argv):
        if arg == f"--{name}" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return default


def process_date():
    override = arg_value("PROCESS_DATE")
    if override:
        if not re.fullmatch(r"\d{8}", override):
            raise ValueError("--PROCESS_DATE must be YYYYMMDD")
        return datetime.strptime(override, "%Y%m%d").replace(tzinfo=EASTERN)
    return datetime.now(EASTERN)


def s3_parts(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Expected S3 URI, got {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def join_s3(prefix, filename):
    return prefix.rstrip("/") + "/" + filename


def parse_crawl_summary(summary_text):
    if not summary_text:
        return None

    summary = json.loads(summary_text)
    partition_add = summary.get("PARTITION", {}).get("ADD")
    if not partition_add:
        return None

    partition_info = json.loads(partition_add)
    details = partition_info.get("Details", {})
    partitions = details.get(VERIFIED_TABLE, [])
    if not partitions:
        return None

    table_update = summary.get("TABLE", {}).get("UPDATE")
    table_count = None
    if table_update:
        table_count = json.loads(table_update).get("Count")

    return {
        "partitions": partitions,
        "partition_count": partition_info.get("Count", len(partitions)),
        "table_count": table_count,
    }


def crawler_partition_registered(glue, yyyymmdd):
    crawls = glue.list_crawls(CrawlerName=CRAWLER_NAME, MaxResults=20).get("Crawls", [])
    for crawl in crawls:
        if crawl.get("State") != "COMPLETED":
            continue

        parsed = parse_crawl_summary(crawl.get("Summary"))
        if not parsed:
            continue

        if yyyymmdd in parsed["partitions"]:
            return {
                "crawl_id": crawl.get("CrawlId"),
                "start_time": crawl.get("StartTime"),
                "partition_count": parsed["partition_count"],
                "table_count": parsed["table_count"],
            }

    return None


def outputs_already_written(s3, uris):
    missing = []
    for uri in uris:
        bucket, key = s3_parts(uri)
        try:
            s3.head_object(Bucket=bucket, Key=key)
        except ClientError as error:
            if error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}:
                missing.append(uri)
                continue
            raise

    return len(missing) == 0, missing


def wait_for_query(athena, query_id):
    while True:
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            return execution
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {query_id} {state}: {reason}")
        time.sleep(10)


def query_has_rows(athena, query, label):
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            "Catalog": ATHENA_CATALOG,
            "Database": ATHENA_DATABASE,
        },
        WorkGroup=ATHENA_WORKGROUP,
    )
    query_id = response["QueryExecutionId"]
    execution = wait_for_query(athena, query_id)
    results = athena.get_query_results(QueryExecutionId=query_id, MaxResults=2)
    rows = results.get("ResultSet", {}).get("Rows", [])
    has_rows = len(rows) > 1
    print(json.dumps({
        "status": "READINESS_QUERY",
        "label": label,
        "query_execution_id": query_id,
        "output_location": execution["ResultConfiguration"].get("OutputLocation"),
        "has_rows": has_rows,
    }))
    return has_rows


def wait_for_source_readiness(athena, yyyymmdd):
    checks = [
        (
            "raw_bankruptcy",
            f"SELECT 1 FROM source_bankruptcy_raw WHERE dt = '{yyyymmdd}' LIMIT 1",
        ),
        (
            "verified",
            f"SELECT 1 FROM verified_bankruptcy_matches WHERE dt = '{yyyymmdd}' LIMIT 1",
        ),
    ]

    for attempt in range(1, READINESS_MAX_ATTEMPTS + 1):
        print(json.dumps({
            "status": "READINESS_ATTEMPT",
            "attempt": attempt,
            "max_attempts": READINESS_MAX_ATTEMPTS,
            "process_date": yyyymmdd,
        }))
        readiness = {
            label: query_has_rows(athena, query, label)
            for label, query in checks
        }
        if all(readiness.values()):
            print(json.dumps({
                "status": "READINESS_SUCCEEDED",
                "attempt": attempt,
                "readiness": readiness,
            }))
            return
        if attempt < READINESS_MAX_ATTEMPTS:
            print(json.dumps({
                "status": "READINESS_WAIT",
                "sleep_seconds": READINESS_SLEEP_SECONDS,
                "readiness": readiness,
            }))
            time.sleep(READINESS_SLEEP_SECONDS)

    raise RuntimeError(
        f"Source tables were not ready for dt={yyyymmdd} after "
        f"{READINESS_MAX_ATTEMPTS} attempts. Main query was not run."
    )


def run_athena_statement(athena, label, query):
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={
            "Catalog": ATHENA_CATALOG,
            "Database": ATHENA_DATABASE,
        },
        WorkGroup=ATHENA_WORKGROUP,
    )
    query_id = response["QueryExecutionId"]
    execution = wait_for_query(athena, query_id)
    print(json.dumps({
        "status": "STATEMENT_SUCCEEDED",
        "label": label,
        "query_execution_id": query_id,
        "output_location": execution["ResultConfiguration"].get("OutputLocation"),
    }))
    return query_id


def refresh_unmatched_view(athena, unmatched_s3_uri):
    query = f"""
CREATE OR REPLACE VIEW bk_unmatched_today AS
SELECT *
FROM bk_unmatched_daily_csv
WHERE "$path" = '{unmatched_s3_uri}'
""".strip()
    print(json.dumps({"status": "REFRESH_VIEW_SQL", "view": "bk_unmatched_today", "sql": query}))
    return run_athena_statement(athena, "refresh_bk_unmatched_today", query)


def run_export_query(athena, s3, label, sql, target_uri):
    print(json.dumps({"status": "EXPORT_SQL", "label": label, "sql": sql}))
    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={
            "Catalog": ATHENA_CATALOG,
            "Database": ATHENA_DATABASE,
        },
        WorkGroup=ATHENA_WORKGROUP,
    )
    query_id = response["QueryExecutionId"]
    print(json.dumps({"status": "SUBMITTED", "label": label, "query_execution_id": query_id}))

    execution = wait_for_query(athena, query_id)
    source_uri = execution["ResultConfiguration"]["OutputLocation"]
    source_bucket, source_key = s3_parts(source_uri)
    target_bucket, target_key = s3_parts(target_uri)

    s3.copy_object(
        Bucket=target_bucket,
        Key=target_key,
        CopySource={"Bucket": source_bucket, "Key": source_key},
        ContentType="text/csv",
        MetadataDirective="REPLACE",
    )

    rows = count_csv_rows(s3, target_uri)
    print(json.dumps({
        "status": "EXPORT_SUCCEEDED",
        "label": label,
        "query_execution_id": query_id,
        "source_uri": source_uri,
        "target_uri": target_uri,
        "row_count": rows,
    }))
    return {
        "query_execution_id": query_id,
        "source_uri": source_uri,
        "target_uri": target_uri,
        "row_count": rows,
    }


def count_csv_rows(s3, uri):
    bucket, key = s3_parts(uri)
    local_path = "/tmp/bankruptcy_unmatched_result.csv"
    s3.download_file(bucket, key, local_path)
    with open(local_path, "r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def main():
    date = process_date()
    yyyymmdd = date.strftime("%Y%m%d")
    mmmdd = date.strftime("%b%d").lower()
    unmatched_target_uri = join_s3(S3_UNMATCHED_PREFIX, f"unmatched_bk_aws_{mmmdd}.csv")
    file_transfer_input_target_uri = join_s3(S3_FileTransfer_INPUT_PREFIX, f"file_transfer_input_{mmmdd}.csv")
    auto_match_target_uri = join_s3(S3_AUTO_MATCH_PREFIX, f"auto_matches_{yyyymmdd}.csv")
    unmatched_sql = UNMATCHED_SQL.format(yyyymmdd=yyyymmdd)
    file_transfer_input_sql = FileTransfer_INPUT_SQL.format(yyyymmdd=yyyymmdd)
    auto_match_sql = AUTO_MATCH_SQL.format(yyyymmdd=yyyymmdd)

    athena = boto3.client("athena", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)
    glue = boto3.client("glue", region_name=REGION)
    skip_crawler_check = arg_value("SKIP_CRAWLER_CHECK", "false").lower() == "true"

    print(json.dumps({
        "status": "STARTED",
        "process_date": yyyymmdd,
        "region": REGION,
        "athena_catalog": ATHENA_CATALOG,
        "athena_database": ATHENA_DATABASE,
        "athena_workgroup": ATHENA_WORKGROUP,
        "crawler_name": CRAWLER_NAME,
        "skip_crawler_check": skip_crawler_check,
        "unmatched_target_uri": unmatched_target_uri,
        "file_transfer_input_target_uri": file_transfer_input_target_uri,
        "auto_match_target_uri": auto_match_target_uri,
    }))

    output_uris = [unmatched_target_uri, file_transfer_input_target_uri, auto_match_target_uri]
    already_written, missing_outputs = outputs_already_written(s3, output_uris)
    if already_written:
        print(json.dumps({
            "status": "SKIPPED",
            "reason": "outputs_already_exist",
            "process_date": yyyymmdd,
            "output_uris": output_uris,
        }))
        return

    if not skip_crawler_check:
        crawler_signal = crawler_partition_registered(glue, yyyymmdd)
        if not crawler_signal:
            print(json.dumps({
                "status": "SKIPPED",
                "reason": "crawler_partition_not_registered",
                "process_date": yyyymmdd,
                "crawler_name": CRAWLER_NAME,
                "missing_outputs": missing_outputs,
            }))
            return

        print(json.dumps({
            "status": "CRAWLER_PARTITION_READY",
            "process_date": yyyymmdd,
            "crawler_signal": crawler_signal,
        }))

    wait_for_source_readiness(athena, yyyymmdd)

    unmatched_export = run_export_query(
        athena,
        s3,
        "unmatched",
        unmatched_sql,
        unmatched_target_uri,
    )
    refresh_query_id = refresh_unmatched_view(athena, unmatched_target_uri)
    file_transfer_input_export = run_export_query(
        athena,
        s3,
        "file_transfer_input",
        file_transfer_input_sql,
        file_transfer_input_target_uri,
    )
    auto_match_export = run_export_query(
        athena,
        s3,
        "auto_match",
        auto_match_sql,
        auto_match_target_uri,
    )
    print(json.dumps({
        "status": "SUCCEEDED",
        "unmatched_query_execution_id": unmatched_export["query_execution_id"],
        "file_transfer_input_query_execution_id": file_transfer_input_export["query_execution_id"],
        "auto_match_query_execution_id": auto_match_export["query_execution_id"],
        "refresh_view_query_execution_id": refresh_query_id,
        "refreshed_view": "bk_unmatched_today",
        "unmatched_target_uri": unmatched_export["target_uri"],
        "unmatched_row_count": unmatched_export["row_count"],
        "file_transfer_input_target_uri": file_transfer_input_export["target_uri"],
        "file_transfer_input_row_count": file_transfer_input_export["row_count"],
        "auto_match_target_uri": auto_match_export["target_uri"],
        "auto_match_row_count": auto_match_export["row_count"],
    }))


if __name__ == "__main__":
    main()
