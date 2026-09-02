# Bankruptcy unmatched automation (no crawler changes)

This workaround does **not** modify `bankruptcy_verification_crawler`.

## How it works

1. The existing Glue trigger `bankruptcy-unmatched` runs every 15 minutes on weekdays (11:00–20:45 UTC, 7:00 AM–4:45 PM EDT), stopping before 5:00 PM Eastern.
2. Each run of `bankruptcy-unmatched-daily` checks recent `bankruptcy_verification_crawler` crawl history via `glue.list_crawls`.
3. If the crawler has **not** yet registered today's `verified_bankruptcy_matches` partition (`PARTITION.ADD` in crawl summary), the job exits quickly with `SKIPPED`.
4. Once the crawler registers the partition, the next scheduled run proceeds with Athena exports.
5. If all three output CSVs already exist for the day, the job skips (idempotent).

## Manual override

Force a run without waiting for crawler signal:

```bash
aws glue start-job-run \
  --job-name bankruptcy-unmatched-daily \
  --arguments '{"--SKIP_CRAWLER_CHECK":"true"}' \
  --profile <AWS_PROFILE> \
  --region eu-west-1
```

## Future upgrade (optional)

When IAM allows `lambda:CreateFunction` and `iam:PassRole`, deploy `lambda_function.py` + `event-pattern.json` via EventBridge for immediate triggering instead of polling. The crawler stays unchanged.

## Cleanup note

`bankruptcy-after-erp11-crawl` conditional Glue trigger was deactivated (it does not work when the crawler runs on its own schedule).
