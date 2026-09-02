"""Smoke-test Oracle connectivity and sample core_data access."""

import os
import sys

import oracledb
import pandas as pd

CLIENT_DIR = r"C:\Users\<USERNAME>\Documents\Codex\oracle-instant-client\instantclient_23_0"
DEFAULT_DSN = "<ORACLE_HOST>:1521/<ORACLE_SERVICE>"


def main() -> int:
    missing = [k for k in ("ORACLE_USER", "ORACLE_PASSWORD") if not os.environ.get(k)]
    if missing:
        print(f"FAIL: missing env vars: {', '.join(missing)}")
        print("Fix: run oraclelogin in PowerShell, or set user-level ORACLE_* env vars.")
        return 1

    dsn = os.environ.get("ORACLE_DSN", DEFAULT_DSN)
    oracledb.init_oracle_client(lib_dir=CLIENT_DIR)
    with oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=dsn,
    ) as conn:
        print("OK: Oracle connection successful")
        identity = pd.read_sql(
            """
            SELECT
                USER AS connected_user,
                SYS_CONTEXT('USERENV', 'DB_NAME') AS db_name,
                SYS_CONTEXT('USERENV', 'SERVICE_NAME') AS service_name
            FROM dual
            """,
            con=conn,
        )
        print(identity.to_string(index=False))
        sample = pd.read_sql(
            "SELECT COUNT(*) AS row_count FROM core_data.company WHERE ROWNUM <= 5",
            con=conn,
        )
        print(sample.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
