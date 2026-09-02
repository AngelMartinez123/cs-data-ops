import json
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CRAWLER_NAME = os.environ.get("CRAWLER_NAME", "bankruptcy_verification_crawler")
JOB_NAME = os.environ.get("JOB_NAME", "bankruptcy-unmatched-daily")
TABLE_NAME = os.environ.get("TABLE_NAME", "verified_bankruptcy_matches")
REGION = os.environ.get("AWS_REGION", "eu-west-1")

glue = boto3.client("glue", region_name=REGION)


def _parse_summary(summary_text):
    if not summary_text:
        return None

    summary = json.loads(summary_text)
    partition_add = summary.get("PARTITION", {}).get("ADD")
    if not partition_add:
        return None

    partition_info = json.loads(partition_add)
    details = partition_info.get("Details", {})
    partitions = details.get(TABLE_NAME, [])
    if not partitions:
        return None

    return {
        "process_date": partitions[0],
        "partition_count": partition_info.get("Count", len(partitions)),
        "table_count": json.loads(summary.get("TABLE", {}).get("UPDATE", "{}")).get("Count"),
    }


def _latest_completed_crawl(crawl_id=None):
    crawls = glue.list_crawls(CrawlerName=CRAWLER_NAME, MaxResults=10).get("Crawls", [])
    if crawl_id:
        for crawl in crawls:
            if crawl.get("CrawlId") == crawl_id:
                return crawl

    for crawl in crawls:
        if crawl.get("State") == "COMPLETED":
            return crawl

    return crawls[0] if crawls else None


def _job_already_succeeded(process_date):
    runs = glue.get_job_runs(JobName=JOB_NAME, MaxResults=20).get("JobRuns", [])
    for run in runs:
        state = run.get("JobRunState")
        if state not in {"SUCCEEDED", "RUNNING", "STARTING", "STOPPING"}:
            continue

        arguments = run.get("Arguments") or {}
        if arguments.get("--PROCESS_DATE") == process_date:
            return state

    return None


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    detail = event.get("detail", {})
    crawler_name = detail.get("crawlerName")
    state = detail.get("state")

    if crawler_name and crawler_name != CRAWLER_NAME:
        return {"skipped": "unexpected crawler", "crawler_name": crawler_name}

    if state and state not in {"Succeeded", "SUCCEEDED"}:
        return {"skipped": "crawler not successful", "state": state}

    crawl_id = detail.get("crawlId")
    crawl = None
    parsed = None

    for attempt in range(1, 4):
        crawl = _latest_completed_crawl(crawl_id=crawl_id)
        if not crawl:
            return {"skipped": "no crawl found"}

        parsed = _parse_summary(crawl.get("Summary"))
        if parsed:
            break

        logger.info("Crawl summary not ready yet; retrying (%s/3)", attempt)
        time.sleep(5)

    if not parsed:
        return {
            "skipped": "no partition add detected",
            "crawl_id": crawl.get("CrawlId"),
            "summary": crawl.get("Summary"),
        }

    process_date = parsed["process_date"]
    existing = _job_already_succeeded(process_date)
    if existing:
        return {
            "skipped": "job already active or completed",
            "process_date": process_date,
            "existing_state": existing,
        }

    response = glue.start_job_run(
        JobName=JOB_NAME,
        Arguments={"--PROCESS_DATE": process_date},
    )

    result = {
        "started": True,
        "job_run_id": response["JobRunId"],
        "process_date": process_date,
        "crawl_id": crawl.get("CrawlId"),
        "partition_count": parsed["partition_count"],
        "table_count": parsed["table_count"],
    }
    logger.info("Started Glue job: %s", json.dumps(result))
    return result
