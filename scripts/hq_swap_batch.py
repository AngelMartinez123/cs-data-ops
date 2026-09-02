"""Generate and validate HQ swap batches from auto_matches QC branch actions."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import oracledb

ROOT = Path(__file__).resolve().parent.parent
CLIENT_DIR = r"C:\Users\<USERNAME>\Documents\Codex\oracle-instant-client\instantclient_23_0"
DEFAULT_DSN = "<ORACLE_HOST>:1521/<ORACLE_SERVICE>"

VALIDATION_SQL = """
WITH pairs AS (
    SELECT :case_num AS case_num,
           :old_hq AS old_hq,
           :new_hq AS new_hq
    FROM dual
)
SELECT p.case_num,
       p.old_hq,
       p.new_hq,
       old_v.location_type AS old_loc,
       new_v.location_type AS new_loc,
       old_r.company_type AS old_rel_type,
       new_r.company_type AS new_rel_type,
       new_v.hq_safe_number AS new_points_to,
       (SELECT COUNT(*)
        FROM core_data.branches_with_parents b
        WHERE b.hq_safe_number = p.old_hq) AS branch_cnt,
       (SELECT COUNT(*)
        FROM core_data.bankruptcy bk
        WHERE bk.safe_number = p.old_hq
          AND bk.deleted_by_editing_tool IS NULL
          AND bk.deleted_by_import IS NULL) AS bk_on_old_hq,
       (SELECT COUNT(*)
        FROM core_data.bankruptcy bk
        WHERE bk.safe_number = p.new_hq
          AND bk.deleted_by_editing_tool IS NULL
          AND bk.deleted_by_import IS NULL) AS bk_on_new_hq
FROM pairs p
JOIN company_search_view old_v ON old_v.safe_number = p.old_hq
JOIN company_search_view new_v ON new_v.safe_number = p.new_hq
LEFT JOIN core_data.company_relationship old_r
  ON old_r.cs_company_id = p.old_hq
 AND old_r.deleted_by_editing_tool IS NULL
 AND old_r.deleted_by_import IS NULL
LEFT JOIN core_data.company_relationship new_r
  ON new_r.cs_company_id = p.new_hq
 AND new_r.deleted_by_editing_tool IS NULL
 AND new_r.deleted_by_import IS NULL
"""


def env(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, name)[0]
    except Exception:
        return None


def load_candidates(analysis_path: Path) -> list[dict]:
    data = json.loads(analysis_path.read_text(encoding="utf-8"))
    rows = []
    for row in data.get("branch_rows", []):
        if "HQ SWAP" not in str(row.get("group_action", "")):
            continue
        rows.append(
            {
                "case_num": row.get("alternate_case_number", ""),
                "old_hq": row.get("current_hq_safe_number", ""),
                "new_hq": row.get("branch_safe_number", ""),
                "defendant_name": row.get("defendant_name", ""),
                "branch_name": row.get("branch_name", ""),
                "hq_name": row.get("current_hq_name", ""),
            }
        )
    return rows


def assess(row: dict) -> tuple[str, list[str]]:
    notes: list[str] = []
    status = "READY"

    if str(row.get("old_loc")) != "1" or str(row.get("new_loc")) != "2":
        status = "BLOCKED"
        notes.append(f"location types old={row.get('old_loc')} new={row.get('new_loc')} (need 1/2)")

    if row.get("old_rel_type") != "HEADQUARTERS":
        status = "BLOCKED"
        notes.append(f"old HQ rel type={row.get('old_rel_type')}")

    if row.get("new_rel_type") != "BRANCH":
        status = "BLOCKED"
        notes.append(f"new HQ rel type={row.get('new_rel_type')}")

    if row.get("new_points_to") != row.get("old_hq"):
        status = "BLOCKED"
        notes.append(f"branch parent={row.get('new_points_to')} expected {row.get('old_hq')}")

    branch_cnt = int(row.get("branch_cnt") or 0)
    if branch_cnt > 1:
        if status == "READY":
            status = "CAUTION"
        notes.append(f"HQ has {branch_cnt} branches; swap promotes one, others follow new HQ")

    if int(row.get("bk_on_old_hq") or 0) > 0:
        if status == "READY":
            status = "CAUTION"
        notes.append(f"BK already on old HQ ({row.get('bk_on_old_hq')} rows)")

    if branch_cnt == 1 and int(row.get("bk_on_old_hq") or 0) == 0:
        notes.append("single-branch HQ, no BK on old HQ — cleanest swap")

    return status, notes


def validate(conn, candidates: list[dict]) -> list[dict]:
    cur = conn.cursor()
    validated: list[dict] = []
    for cand in candidates:
        cur.execute(
            VALIDATION_SQL,
            case_num=cand["case_num"],
            old_hq=cand["old_hq"],
            new_hq=cand["new_hq"],
        )
        cols = [item[0].lower() for item in cur.description]
        db_row = dict(zip(cols, cur.fetchone()))
        merged = {**cand, **db_row}
        status, notes = assess(merged)
        merged["swap_status"] = status
        merged["swap_notes"] = notes
        validated.append(merged)
    return validated


def render_sql(rows: list[dict], include_bulk: bool = False) -> str:
    ready = [r for r in rows if r["swap_status"] in {"READY", "CAUTION"}]
    lines = [
        "-- HQ swap batch from auto_matches QC",
        f"-- Generated {date.today().isoformat()}",
        "-- Procedure: editing_api.pkg_entity_relations.p_swap_hq",
        "--   i_safe_number_oldhq => current HQ (loc 1)",
        "--   i_safe_number_newhq => branch to promote (loc 2)",
        "",
        "SET SERVEROUTPUT ON SIZE UNLIMITED;",
        "",
    ]

    if include_bulk:
        lines.extend(
            [
                "BEGIN",
                "  EXECUTE IMMEDIATE 'TRUNCATE TABLE reporting_utils.gtt_swap_hq';",
                "  EXECUTE IMMEDIATE 'TRUNCATE TABLE reporting_utils.gtt_bulk_edit_log';",
                "END;",
                "/",
                "",
            ]
        )
        for row in ready:
            lines.append(
                "INSERT INTO reporting_utils.gtt_swap_hq (old_hq_sn, new_hq_sn) "
                f"VALUES ('{row['old_hq']}', '{row['new_hq']}');  -- case {row['case_num']}"
            )
        lines.extend(
            [
                "",
                "COMMIT;",
                "",
                "BEGIN",
                "  reporting_utils.pd_bulk_swap_hq;",
                "END;",
                "/",
                "",
                "-- After bulk run, inspect errors (if any remain before proc cleanup):",
                "-- SELECT * FROM reporting_utils.gtt_bulk_edit_log;",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "DECLARE",
            "  v_old_hq core_data.company.safe_number%TYPE;",
            "  v_new_hq core_data.company.safe_number%TYPE;",
            "  v_success NUMBER := 0;",
            "  v_fail NUMBER := 0;",
            "BEGIN",
            "  FOR r IN (",
            "    SELECT case_num, old_hq, new_hq FROM (",
        ]
    )
    unions = []
    for row in ready:
        unions.append(
            f"      SELECT '{row['case_num']}' AS case_num, "
            f"'{row['old_hq']}' AS old_hq, '{row['new_hq']}' AS new_hq FROM dual"
        )
    lines.append("\n      UNION ALL\n".join(unions))
    lines.extend(
        [
            "    ) ORDER BY case_num",
            "  ) LOOP",
            "    v_old_hq := r.old_hq;",
            "    v_new_hq := r.new_hq;",
            "    BEGIN",
            "      dbms_output.put_line('START case=' || r.case_num || ' old_hq=' || v_old_hq || ' new_hq=' || v_new_hq);",
            "      editing_api.pkg_entity_relations.p_swap_hq(",
            "        i_safe_number_oldhq => v_old_hq,",
            "        i_safe_number_newhq => v_new_hq",
            "      );",
            "      v_success := v_success + 1;",
            "      dbms_output.put_line('SUCCESS case=' || r.case_num);",
            "    EXCEPTION",
            "      WHEN OTHERS THEN",
            "        v_fail := v_fail + 1;",
            "        dbms_output.put_line('FAILED case=' || r.case_num || ' err=' || SQLERRM);",
            "    END;",
            "  END LOOP;",
            "  dbms_output.put_line('DONE success=' || v_success || ' fail=' || v_fail);",
            "END;",
            "/",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="HQ swap batch from auto_matches QC.")
    parser.add_argument(
        "--analysis",
        type=Path,
        help="Path to *_qc_analysis.json (default: latest in work/)",
    )
    parser.add_argument(
        "--output-sql",
        type=Path,
        help="Write loop SQL here (default: sql/group/auto_matches_hq_swap_YYYYMMDD.sql)",
    )
    parser.add_argument(
        "--bulk",
        action="store_true",
        help="Generate REPORTING_UTILS.PD_BULK_SWAP_HQ variant instead of per-row loop.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only print validation table; do not write SQL.",
    )
    args = parser.parse_args()

    if args.analysis:
        analysis_path = args.analysis
    else:
        work = ROOT / "work"
        candidates = sorted(work.glob("**/auto_matches_*_qc_analysis.json"), reverse=True)
        if not candidates:
            print("No qc_analysis.json found under work/", file=sys.stderr)
            return 1
        analysis_path = candidates[0]

    swap_rows = load_candidates(analysis_path)
    if not swap_rows:
        print(f"No HQ SWAP rows in {analysis_path}", file=sys.stderr)
        return 1

    try:
        oracledb.init_oracle_client(lib_dir=CLIENT_DIR)
    except Exception:
        pass

    user = env("ORACLE_USER")
    password = env("ORACLE_PASSWORD")
    if not user or not password:
        print("Missing ORACLE_USER / ORACLE_PASSWORD", file=sys.stderr)
        return 1

    with oracledb.connect(
        user=user,
        password=password,
        dsn=env("ORACLE_DSN") or DEFAULT_DSN,
    ) as conn:
        validated = validate(conn, swap_rows)

    print(f"Loaded {len(validated)} HQ SWAP candidates from {analysis_path}\n")
    for row in validated:
        print(
            f"{row['swap_status']:8} case={row['case_num']} "
            f"old={row['old_hq']} new={row['new_hq']} branches={row.get('branch_cnt')}"
        )
        for note in row["swap_notes"]:
            print(f"         - {note}")
        print()

    counts = {}
    for row in validated:
        counts[row["swap_status"]] = counts.get(row["swap_status"], 0) + 1
    print("Summary:", counts)

    if args.validate_only:
        return 0

    sql_path = args.output_sql or (
        ROOT / "sql" / "group" / f"auto_matches_hq_swap_{date.today().strftime('%Y%m%d')}.sql"
    )
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(render_sql(validated, include_bulk=args.bulk), encoding="utf-8")
    print(f"Wrote {sql_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
