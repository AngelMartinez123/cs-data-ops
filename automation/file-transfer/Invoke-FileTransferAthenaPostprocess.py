"""Publish an FileTransfer result, run the daily Athena sequence, and export bk candidates."""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


FINAL_SQL = r"""
WITH base AS (
    SELECT
        b.*,
        substr(entity_type, 1, 1) AS defendant_type
    FROM source_bankruptcy_raw b
    WHERE dt = '{date_id}'
      AND delete_flag IS NULL
),

valid_cases AS (
    SELECT cust_court AS courtid, case_number
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
    SELECT v.list_of_unique_ids, uid
    FROM verified_bankruptcy_matches v
    CROSS JOIN UNNEST(v.list_of_unique_ids) AS t(uid)
    WHERE v.dt = '{date_id}'
),

cte AS (
    SELECT
        b.*,
        filter(v.list_of_unique_ids, x -> x LIKE 'US%') AS safe_number_list
    FROM base1 b
    JOIN b_expanded v ON b.unique_id = v.uid
    WHERE cardinality(filter(v.list_of_unique_ids, x -> x LIKE 'US%')) = 1
),

excluded_cases AS (
    SELECT DISTINCT unique_case_id
    FROM cte
),

todays_candidates AS (
    SELECT unique_id, safe_number, match_algo
    FROM daily_unmatched_candidates
    WHERE "$path" LIKE '%file_transfer_matches_{date_id}%'
),

bankruptcy_ranked AS (
    SELECT
        m.*,
        row_number() OVER (PARTITION BY m.unique_id ORDER BY m.dt DESC) AS rn
    FROM source_bankruptcy_raw m
),

bankruptcy_latest AS (
    SELECT *
    FROM bankruptcy_ranked
    WHERE rn = 1
)

SELECT
    c.location_type,
    b.cust_court,
    b.alternate_case,
    CAST(TRY(date_parse(NULLIF(CAST(b.filing_date AS varchar), ''), '%Y%m%d')) AS DATE) AS filing_date,
    CAST(TRY(date_parse(NULLIF(CAST(b.release_date AS varchar), ''), '%Y%m%d')) AS DATE) AS release_date,
    b.cust_file_type,
    b.original_chapter,
    d.safe_number,
    b.defendant_name,
    c.company_name,
    b.defendant_address,
    c.address AS company_address,
    b.defendant_city,
    c.city AS company_city,
    b.defendant_state,
    c.state AS company_state,
    b.defendant_zip_code,
    c.zip AS company_zip,
    CAST(NULL AS varchar) AS validated_candidate,
    CAST(NULL AS varchar) AS notes,
    b.rmsid,
    b.unique_case_id,
    b.unique_id,
    b.dt,
    d.match_algo
FROM todays_candidates d
LEFT JOIN bankruptcy_latest b ON b.unique_id = d.unique_id
LEFT JOIN source_company_index c
  ON d.safe_number = c.safe_number
 AND c.dt = (SELECT MAX(dt) FROM source_company_index)
 AND c.deleted_by_editing_tool IS NULL
 AND c.deleted_by_import IS NULL
WHERE NOT EXISTS (
    SELECT 1
    FROM excluded_cases e
    WHERE e.unique_case_id = b.unique_case_id
)
ORDER BY alternate_case DESC
""".strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Process date as YYYYMMDD")
    parser.add_argument("--file-transfer-file", required=True, type=Path)
    parser.add_argument("--local-output", required=True, type=Path)
    parser.add_argument("--profile", default="<AWS_PROFILE>")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument("--bucket", default="<S3_BUCKET>")
    parser.add_argument("--candidates-prefix", default="<USER_PREFIX>/bankruptcy_candidates")
    parser.add_argument("--bk-prefix", default="<USER_PREFIX>/bk_file")
    parser.add_argument("--bk-output-name", required=True)
    parser.add_argument("--catalog", default="AwsDataCatalog")
    parser.add_argument("--database", default="<ATHENA_DATABASE>")
    parser.add_argument("--workgroup", default="<ATHENA_WORKGROUP>")
    parser.add_argument("--resume-existing", action="store_true")
    return parser.parse_args()


def s3_parts(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def wait_for_query(athena, query_id: str) -> dict:
    while True:
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            return execution
        if state in {"FAILED", "CANCELLED"}:
            reason = execution["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {query_id} {state}: {reason}")
        time.sleep(3)


def run_query(athena, args: argparse.Namespace, label: str, sql: str) -> dict:
    response = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Catalog": args.catalog, "Database": args.database},
        WorkGroup=args.workgroup,
    )
    query_id = response["QueryExecutionId"]
    print(json.dumps({"status": "QUERY_SUBMITTED", "label": label, "query_id": query_id}))
    execution = wait_for_query(athena, query_id)
    print(json.dumps({"status": "QUERY_SUCCEEDED", "label": label, "query_id": query_id}))
    return execution


def upload_idempotent(s3, local_path: Path, bucket: str, key: str) -> None:
    local_size = local_path.stat().st_size
    try:
        existing = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
    else:
        if existing["ContentLength"] != local_size:
            raise RuntimeError(
                f"S3 target exists with a different size and was not overwritten: s3://{bucket}/{key}"
            )
        print(json.dumps({"status": "UPLOAD_REUSED", "uri": f"s3://{bucket}/{key}", "size": local_size}))
        return

    s3.upload_file(str(local_path), bucket, key, ExtraArgs={"ContentType": "text/csv"})
    uploaded = s3.head_object(Bucket=bucket, Key=key)
    if uploaded["ContentLength"] != local_size:
        raise RuntimeError("Uploaded FileTransfer object failed size verification.")
    print(json.dumps({"status": "UPLOAD_SUCCEEDED", "uri": f"s3://{bucket}/{key}", "size": local_size}))


def count_csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


def main() -> None:
    args = parse_args()
    if len(args.date) != 8 or not args.date.isdigit():
        raise ValueError("--date must be YYYYMMDD")
    expected_file_transfer_name = f"file_transfer_matches_{args.date}.csv"
    if args.file_transfer_file.name.lower() != expected_file_transfer_name.lower():
        raise ValueError(f"FileTransfer filename must be {expected_file_transfer_name}")
    if not args.file_transfer_file.is_file() or args.file_transfer_file.stat().st_size <= 0:
        raise FileNotFoundError(f"FileTransfer result is missing or empty: {args.file_transfer_file}")

    session = boto3.Session(profile_name=args.profile)
    s3 = session.client("s3", region_name=args.region)
    athena = session.client("athena", region_name=args.region)

    candidates_key = f"{args.candidates_prefix.strip('/')}/{expected_file_transfer_name}"
    upload_idempotent(s3, args.file_transfer_file, args.bucket, candidates_key)
    target_key = f"{args.bk_prefix.strip('/')}/{args.bk_output_name}"

    if args.resume_existing:
        try:
            existing_final = s3.head_object(Bucket=args.bucket, Key=target_key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                raise
        else:
            remote_size = existing_final["ContentLength"]
            if args.local_output.exists():
                if args.local_output.stat().st_size != remote_size:
                    raise RuntimeError("Existing local and S3 final outputs differ; neither was overwritten.")
            else:
                args.local_output.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(args.bucket, target_key, str(args.local_output))
            print(
                json.dumps(
                    {
                        "status": "RESUMED_EXISTING_FINAL",
                        "final_s3_uri": f"s3://{args.bucket}/{target_key}",
                        "local_output": str(args.local_output),
                        "row_count": count_csv_rows(args.local_output),
                        "size": remote_size,
                    }
                )
            )
            return

    view_sql = f"""
CREATE OR REPLACE VIEW daily_unmatched_candidates_today AS
SELECT *
FROM daily_unmatched_candidates
WHERE \"$path\" LIKE '%file_transfer_matches_{args.date}%'
""".strip()
    run_query(athena, args, "refresh_view", view_sql)

    # Run the requested view SELECT in sequence and retain its Athena result for audit.
    run_query(athena, args, "select_view", "SELECT * FROM daily_unmatched_candidates_today")

    final_execution = run_query(
        athena,
        args,
        "final_candidates",
        FINAL_SQL.format(date_id=args.date),
    )
    result_uri = final_execution["ResultConfiguration"]["OutputLocation"]
    result_bucket, result_key = s3_parts(result_uri)
    try:
        existing = s3.head_object(Bucket=args.bucket, Key=target_key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
    else:
        raise RuntimeError(
            f"Final S3 target already exists and was not overwritten: s3://{args.bucket}/{target_key} "
            f"({existing['ContentLength']} bytes)"
        )

    s3.copy_object(
        Bucket=args.bucket,
        Key=target_key,
        CopySource={"Bucket": result_bucket, "Key": result_key},
        ContentType="text/csv",
        MetadataDirective="REPLACE",
    )
    args.local_output.parent.mkdir(parents=True, exist_ok=True)
    if args.local_output.exists():
        raise RuntimeError(f"Local final output already exists and was not overwritten: {args.local_output}")
    s3.download_file(args.bucket, target_key, str(args.local_output))
    row_count = count_csv_rows(args.local_output)
    final_size = args.local_output.stat().st_size
    remote_size = s3.head_object(Bucket=args.bucket, Key=target_key)["ContentLength"]
    if final_size != remote_size:
        raise RuntimeError("Final local/S3 size verification failed.")

    print(
        json.dumps(
            {
                "status": "SUCCEEDED",
                "date": args.date,
                "file_transfer_s3_uri": f"s3://{args.bucket}/{candidates_key}",
                "final_s3_uri": f"s3://{args.bucket}/{target_key}",
                "local_output": str(args.local_output),
                "row_count": row_count,
                "size": final_size,
            }
        )
    )


if __name__ == "__main__":
    main()
