"""Combined local preflight: Oracle smoke test + AWS STS. MCP checked separately by agent."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def check_oracle() -> tuple[bool, str, str | None]:
    test_script = SCRIPT_DIR / "test_oracle_connection.py"
    proc = subprocess.run(
        [sys.executable, str(test_script)],
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return True, "Oracle connection OK", output.strip() or None
    fix = "Run oraclelogin in PowerShell, or set user-level ORACLE_USER / ORACLE_PASSWORD."
    return False, "Oracle connection failed", fix


def check_aws(profile: str = "<AWS_PROFILE>") -> tuple[bool, str, str | None]:
    try:
        proc = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--profile", profile],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, "AWS CLI not found", (
            f"Install AWS CLI, then: aws-azure-login.cmd --profile {profile} --mode=gui --no-sandbox"
        )

    if proc.returncode == 0:
        try:
            data = json.loads(proc.stdout)
            account = data.get("Account", "?")
            arn = data.get("Arn", "?")
            return True, f"AWS OK (account {account})", arn
        except json.JSONDecodeError:
            return True, "AWS OK", proc.stdout.strip()

    fix = f"aws-azure-login.cmd --profile {profile} --mode=gui --no-sandbox"
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, "AWS STS failed", f"{fix}\n{detail}".strip()


def main() -> int:
    print("Data Operations preflight")
    print(f"Workspace: {ROOT}")
    print()

    results: list[tuple[str, bool, str, str | None]] = []

    aws_ok, aws_msg, aws_detail = check_aws()
    results.append(("AWS", aws_ok, aws_msg, aws_detail))

    ora_ok, ora_msg, ora_detail = check_oracle()
    results.append(("Oracle", ora_ok, ora_msg, ora_detail))

    # MCP must be invoked by the agent; document expected tool here.
    results.append(
        (
            "Data Operations Dev MCP",
            False,
            "Agent must call verify_data_access",
            "Requires VPN + company-data MCP MCP enabled. Fail if tool errors or returns no access.",
        )
    )

    exit_code = 0
    for name, ok, msg, detail in results:
        icon = "OK" if ok else "FAIL"
        if name == "Data Operations Dev MCP":
            icon = "CHECK"
        print(f"[{icon}] {name}: {msg}")
        if detail and (not ok or name == "Data Operations Dev MCP"):
            for line in detail.splitlines():
                print(f"      {line}")
        if not ok and name != "Data Operations Dev MCP":
            exit_code = 1
    print()
    print("Agent: after this script, call MCP verify_data_access and report VPN/MCP status.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
