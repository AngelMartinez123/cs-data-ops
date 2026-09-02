"""Run a read-only Oracle SELECT and print results as CSV or table."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import oracledb
import pandas as pd

CLIENT_DIR = r"C:\Users\<USERNAME>\Documents\Codex\oracle-instant-client\instantclient_23_0"
DEFAULT_DSN = "<ORACLE_HOST>:1521/<ORACLE_SERVICE>"


def connect():
    missing = [k for k in ("ORACLE_USER", "ORACLE_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"Missing env vars: {', '.join(missing)}. Run oraclelogin first."
        )
    oracledb.init_oracle_client(lib_dir=CLIENT_DIR)
    return oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ.get("ORACLE_DSN", DEFAULT_DSN),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an Oracle SELECT query.")
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        help="Path to a .sql file containing the query.",
    )
    parser.add_argument(
        "--query",
        "-q",
        help="Inline SQL query string.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Optional CSV output path.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional row limit wrapper (adds ROWNUM guard for SELECTs).",
    )
    args = parser.parse_args()

    if args.file and args.query:
        print("Use either --file or --query, not both.", file=sys.stderr)
        return 2
    if args.file:
        sql = args.file.read_text(encoding="utf-8", errors="replace").strip()
    elif args.query:
        sql = args.query.strip()
    else:
        print("Provide --file or --query.", file=sys.stderr)
        return 2

    if not sql:
        print("Empty query.", file=sys.stderr)
        return 2

    lowered = sql.lower()
    if any(
        token in lowered
        for token in (" insert ", " update ", " delete ", " merge ", " drop ", " truncate ")
    ):
        print("Refusing non-SELECT SQL.", file=sys.stderr)
        return 2

    if args.limit and "rownum" not in lowered:
        sql = f"SELECT * FROM ({sql}) WHERE ROWNUM <= {args.limit}"

    with connect() as conn:
        df = pd.read_sql(sql, con=conn)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.output, index=False)
        print(f"Wrote {len(df)} rows to {args.output}")
    else:
        print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
