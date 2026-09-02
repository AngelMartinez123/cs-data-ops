"""Auto-matches QC pipeline: S3/local CSV -> Oracle enrich -> analyze -> workbooks."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import oracledb
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

ROOT = Path(__file__).resolve().parent.parent
CLIENT_DIR = r"C:\Users\<USERNAME>\Documents\Codex\oracle-instant-client\instantclient_23_0"
DEFAULT_DSN = "<ORACLE_HOST>:1521/<ORACLE_SERVICE>"
DEFAULT_S3_PREFIX = "s3://<S3_BUCKET>/<USER_PREFIX>/auto_matches/"

NAVY = "18324A"
WHITE = "FFFFFF"
LINE = "D6DCE2"
RED = "F4CCCC"
YELLOW = "FFF2CC"
BLUE = "DDEBF7"
GREEN = "DDEFE4"
HIGH_ACTION = "F4CCCC"
BK_COPY = "D9EAD3"

LEGAL_FORMS = {
    "LLC", "INC", "INCORPORATED", "CORP", "CORPORATION", "LTD", "LIMITED", "LP",
    "LLP", "PLLC", "PC", "CO", "COMPANY", "PARTNERSHIP", "TRUST",
}

QC_HEADERS = [
    "source_row", "severity", "flag", "recommended_action", "alternate_case_number",
    "defendant_rmsid", "unique_case_id", "safe_number", "defendant_name", "company_name",
    "oracle_company_name", "location_type", "branch_count", "in_group_structure",
    "corp_file_key", "hq_safe_number", "hq_name", "hq_corp_file_key", "same_sos_chk",
    "company_id", "parent_company_id", "filing_date", "release_date", "name_score", "note",
]

BRANCH_HEADERS = [
    "source_row", "alternate_case_number", "defendant_name", "status",
    "group_action", "bankruptcy_action", "branch_safe_number", "branch_name",
    "current_hq_safe_number", "current_hq_name", "target_safe_number", "target_name",
    "branch_state", "hq_state", "same_sos_chk", "name_score_branch_hq",
    "address_score_branch", "address_score_hq", "address_match_safe",
    "rank_winner_safe", "rank_branch_rn", "rank_hq_rn",
    "filing_date", "release_date", "confidence", "evidence", "final_reason",
    "caution_or_next_step",
]


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


def norm(s: str) -> str:
    s = (s or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_suffix(s: str) -> str:
    words = norm(s).split()
    while words and words[-1] in LEGAL_FORMS:
        words.pop()
    return " ".join(words)


def name_score(a: str, b: str) -> float:
    aa, bb = strip_suffix(a), strip_suffix(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    ta, tb = set(aa.split()), set(bb.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def clean(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def oracle_rows(cursor) -> list[dict]:
    cols = [item[0].lower() for item in cursor.description]
    return [{key: clean(value) for key, value in zip(cols, row)} for row in cursor.fetchall()]


def first(rows: list[dict]) -> dict:
    return rows[0] if rows else {}


def active_bk(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not r.get("deleted_by_import") and not r.get("deleted_by_editing_tool")]


def severity_rank(sev: str) -> int:
    return {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}.get(sev, 9)


def download_s3(s3_uri: str, dest: Path, profile: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["aws", "s3", "cp", s3_uri, str(dest), "--profile", profile],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"S3 download failed:\n{proc.stderr or proc.stdout}")
    print(f"Downloaded {s3_uri} -> {dest}")


def resolve_input_path(args: argparse.Namespace, out_dir: Path) -> Path:
    if args.input:
        return Path(args.input)
    stamp = args.date.replace("-", "") if args.date else date.today().strftime("%Y%m%d")
    filename = f"auto_matches_{stamp}.csv"
    if args.s3_uri:
        s3_uri = args.s3_uri
    else:
        prefix = args.s3_prefix.rstrip("/")
        s3_uri = f"{prefix}/{filename}"
    local = out_dir / filename
    download_s3(s3_uri, local, args.aws_profile)
    return local


def enrich_records(records: list[dict]) -> dict:
    safes = sorted({r["safe_number"].strip() for r in records if r.get("safe_number", "").strip()})
    cases = sorted(
        {r["alternate_case_number"].strip() for r in records if r.get("alternate_case_number", "").strip()}
    )
    result = {
        "records": records,
        "company": {},
        "hq": {},
        "relationship": {},
        "bankruptcy": {},
        "same_sos": {},
        "meta": {"rows": len(records), "safe_numbers": len(safes), "cases": len(cases)},
    }

    try:
        oracledb.init_oracle_client(lib_dir=CLIENT_DIR)
    except Exception:
        pass

    user = env("ORACLE_USER")
    password = env("ORACLE_PASSWORD")
    if not user or not password:
        raise SystemExit("Missing ORACLE_USER / ORACLE_PASSWORD. Run oraclelogin first.")

    with oracledb.connect(
        user=user,
        password=password,
        dsn=env("ORACLE_DSN") or DEFAULT_DSN,
    ) as conn:
        conn.call_timeout = 30000
        cur = conn.cursor()

        company_sql = """
            select *
            from (
                select reporting_utils.fn_br_count_for_hq(a.safe_number) as cnt_br,
                       case when a.safe_number in (
                           select safe_number
                           from core_data.group_structure
                           where safe_number is not null
                       ) then 'Y' else 'N' end as sn_in_grpstr,
                       a.safe_number, a.company_name, a.address, a.city, a.state, a.zip,
                       a.location_type, a.hq_safe_number, a.hq_name, a.corp_file_key,
                       a.is_hidden, a.is_deleted_date
                from company_search_view a
                where a.safe_number = :safe
            )
            where rownum <= 25
        """

        for safe in safes:
            cur.execute(company_sql, safe=safe)
            company_rows = oracle_rows(cur)
            result["company"][safe] = company_rows

            cur.execute(
                """
                select parentid, companyid, cs_company_id, company_name, company_type,
                       deleted_by_editing_tool, deleted_by_import, dedupe_override
                from core_data.company_relationship
                where cs_company_id = :safe
                order by nvl(deleted_by_editing_tool, date '9999-12-31'),
                         nvl(deleted_by_import, date '9999-12-31')
                """,
                safe=safe,
            )
            result["relationship"][safe] = oracle_rows(cur)

            hq_safe = next((r.get("hq_safe_number") for r in company_rows if r.get("hq_safe_number")), None)
            if hq_safe and hq_safe not in result["hq"]:
                cur.execute(company_sql, safe=hq_safe)
                result["hq"][hq_safe] = oracle_rows(cur)
            if hq_safe:
                try:
                    cur.execute(
                        "select grouping_data.fn_has_same_sos_chk(:branch_safe, :hq_safe) as has_same_sos_chk from dual",
                        branch_safe=safe,
                        hq_safe=hq_safe,
                    )
                    result["same_sos"][safe] = cur.fetchone()[0]
                except Exception as exc:
                    result["same_sos"][safe] = f"ERROR: {str(exc).splitlines()[0]}"

        for case in cases:
            cur.execute(
                """
                select courtid, other_case_number, safe_number, filing_date, release_date,
                       action_type_id, defendant_name, alias_type, create_date,
                       row_unique_id, deleted_by_import, deleted_by_editing_tool
                from core_data.bankruptcy
                where other_case_number = :case
                order by create_date desc nulls last
                """,
                case=case,
            )
            result["bankruptcy"][case] = oracle_rows(cur)

    return result


def same_sos_strong(val: str) -> bool:
    return str(val or "").upper() in {"Y", "HAS SAME SOS"}


def same_sos_loose(val: str) -> bool:
    return str(val or "").upper() in {"Y", "HAS SAME SOS", "HAS RELATED SOS"}


ADDR_STOP = {
    "STE", "ST", "SUITE", "STREET", "RD", "ROAD", "DR", "DRIVE", "AVE", "AVENUE",
    "BLVD", "LN", "LANE", "CT", "COURT", "HWY", "HIGHWAY", "UNIT", "FL", "FLOOR",
    "BLDG", "BUILDING", "STE.", "ST.", "DR.", "RD.", "AVE.", "BLVD.", "N", "S", "E", "W",
    "NE", "NW", "SE", "SW", "NORTH", "SOUTH", "EAST", "WEST",
}


def norm_street(s: str) -> str:
    s = norm(s)
    s = s.replace(" P O BOX ", " PO BOX ")
    tokens = []
    for token in s.split():
        if token in ADDR_STOP:
            continue
        if token.isdigit() and len(token) <= 2:
            continue
        tokens.append(token)
    return " ".join(tokens)


def defendant_address_parts(rec: dict) -> dict[str, str]:
    return {
        "street": norm_street(rec.get("defendant_address", "")),
        "city": norm(rec.get("defendant_city", "")),
        "state": norm(rec.get("defendant_state", "")),
        "zip": re.sub(r"\D", "", rec.get("defendant_zip", ""))[:5],
    }


def company_address_parts(comp: dict) -> dict[str, str]:
    return {
        "street": norm_street(comp.get("address", "")),
        "city": norm(comp.get("city", "")),
        "state": norm(comp.get("state", "")),
        "zip": re.sub(r"\D", "", comp.get("zip", ""))[:5],
    }


def address_match_score(left: dict[str, str], right: dict[str, str]) -> float:
    if left["state"] and right["state"] and left["state"] != right["state"]:
        return 0.0
    score = 0.0
    if left["city"] and right["city"] and left["city"] == right["city"]:
        score += 0.25
    if left["zip"] and right["zip"] and left["zip"] == right["zip"]:
        score += 0.15
    left_tokens = set(left["street"].split())
    right_tokens = set(right["street"].split())
    if left_tokens and right_tokens:
        score += 0.6 * (len(left_tokens & right_tokens) / len(left_tokens | right_tokens))
    elif left["street"] and right["street"] and left["street"] == right["street"]:
        score += 0.6
    return round(min(score, 1.0), 3)


def rank_table_sql(case_key: str, safes: list[str]) -> str:
    unions = " UNION ALL ".join(
        f"SELECT '{case_key}' AS grouping_key, '{safe}' AS this_safe_number FROM dual"
        for safe in safes
    )
    return f"({unions})"


def rank_hq_candidates(conn, case_key: str, safes: list[str]) -> list[dict]:
    if len(safes) < 2:
        return []
    suffix = str(int(time.time() * 1000))[-7:]
    out_table = re.sub(r"[^A-Z0-9_]", "_", f"RQ_{case_key}_{suffix}")[:28]
    table = rank_table_sql(case_key, safes)
    cur = conn.cursor()
    try:
        cur.execute(f"DROP TABLE grouping_data.{out_table} PURGE")
    except Exception:
        pass
    cur.callproc(
        "GROUPING_DATA.P_RANK_SNS_FOR_HQ",
        ["grouping_key", "this_safe_number", table, out_table],
    )
    cur.execute(
        f"""
        SELECT this_safe_number, rn, has_sos, has_sos_4rank, company_type,
               count_branches, bk_date_in_scope, annual_sales_amount,
               estimated_number_of_employees, is_po_box_4rank
        FROM grouping_data.{out_table}
        ORDER BY rn
        """
    )
    cols = [item[0].lower() for item in cur.description]
    rows = [{key: clean(value) for key, value in zip(cols, row)} for row in cur.fetchall()]
    try:
        cur.execute(f"DROP TABLE grouping_data.{out_table} PURGE")
        conn.commit()
    except Exception:
        pass
    return rows


def enrich_hq_ranks(records: list[dict], company: dict, skip_rank: bool = False) -> dict[str, list[dict]]:
    pairs: dict[str, tuple[str, str]] = {}
    for rec in records:
        safe = rec.get("safe_number", "").strip()
        comp = first(company.get(safe, []))
        if str(comp.get("location_type") or rec.get("location_type") or "") != "2":
            continue
        hq_safe = (comp.get("hq_safe_number") or "").strip()
        if not hq_safe or hq_safe == safe:
            continue
        case_key = rec.get("alternate_case_number", "") or f"ROW{safe}"
        pairs[case_key] = (safe, hq_safe)

    if skip_rank or not pairs:
        return {}

    try:
        oracledb.init_oracle_client(lib_dir=CLIENT_DIR)
    except Exception:
        pass

    user = env("ORACLE_USER")
    password = env("ORACLE_PASSWORD")
    if not user or not password:
        return {}

    ranks: dict[str, list[dict]] = {}
    with oracledb.connect(
        user=user,
        password=password,
        dsn=env("ORACLE_DSN") or DEFAULT_DSN,
    ) as conn:
        conn.call_timeout = 120000
        for case_key, (branch_safe, hq_safe) in pairs.items():
            try:
                ranks[case_key] = rank_hq_candidates(conn, case_key, [branch_safe, hq_safe])
            except Exception as exc:
                ranks[case_key] = [{"error": str(exc).splitlines()[0]}]
    return ranks


def recommend_action(sev: str, flag: str, loc: str, safe: str, hq_safe: str) -> str:
    if flag == "BRANCH_BK_MATCH":
        if sev == "HIGH":
            return "Review branch/HQ identity; likely separation or promote branch to HQ before/after BK handling."
        return f"Review whether BK should route to HQ {hq_safe}; no branch SAFE import unless full BR/HQ rule is satisfied."
    if flag == "CASE_ALREADY_ON_DIFFERENT_SAFE":
        return "Compare Oracle BK row and auto match; likely skip or reroute to existing BK SAFE."
    if flag in {"EVENT_ALREADY_LOADED", "CASE_ALREADY_LOADED"}:
        return "Skip duplicate import unless current row carries a genuinely missing event."
    if flag == "LOW_NAME_SIMILARITY":
        return "PACER/legal-name review before import; possible bad match or DBA alias."
    if flag == "MULTI_ROW_CASE_FAMILY":
        return "Review duplicate/legal debtor rows together; keep legal debtor/event-bearing row."
    if flag == "SAME_ADDRESS_CLUSTER":
        return "Possible group-structure review; check PACER associated cases before moving groups."
    return "Review."


def classify_branch_actions(
    rec: dict,
    comp: dict,
    hq: dict,
    bk_rows: list[dict],
    same_sos: str,
    branch_hq_score: float,
    rank_rows: list[dict],
    branch_addr_score: float,
    hq_addr_score: float,
) -> tuple[str, str, str, str, str, str, str, str, str | int | None, str | int | None]:
    safe = rec["safe_number"]
    hq_safe = comp.get("hq_safe_number") or ""
    active = active_bk(bk_rows)
    bk_on_branch = any(r.get("safe_number") == safe for r in active)
    bk_on_hq = any(r.get("safe_number") == hq_safe for r in active) if hq_safe else False

    rank_winner = ""
    rank_branch_rn: str | int | None = None
    rank_hq_rn: str | int | None = None
    valid_rank = rank_rows and not rank_rows[0].get("error")
    if valid_rank:
        rank_winner = rank_rows[0].get("this_safe_number", "")
        for row in rank_rows:
            if row.get("this_safe_number") == safe:
                rank_branch_rn = row.get("rn")
            if row.get("this_safe_number") == hq_safe:
                rank_hq_rn = row.get("rn")

    addr_match_safe = safe if branch_addr_score >= hq_addr_score else hq_safe
    addr_delta = round(branch_addr_score - hq_addr_score, 3)
    distinct_entity = (not same_sos_loose(same_sos)) and branch_hq_score < 0.7
    cross_state = bool(comp.get("state") and hq.get("state") and comp.get("state") != hq.get("state"))
    diff_city = bool(
        comp.get("city")
        and hq.get("city")
        and norm(comp.get("city", "")) != norm(hq.get("city", ""))
    )
    related_not_same = same_sos_loose(same_sos) and not same_sos_strong(same_sos)

    if branch_addr_score >= 0.7 and hq_addr_score < 0.55 and branch_hq_score >= 0.5:
        if cross_state or (related_not_same and diff_city and branch_hq_score >= 0.85):
            return (
                "REVIEW",
                "NO GROUP CHANGE",
                "REVIEW COPY TO HQ VS PROMOTE",
                "Medium",
                f"Branch address matches debtor ({branch_addr_score}) better than HQ ({hq_addr_score}), but cross-state or related-SOS/same-name/different-city needs manual review.",
                f"States branch={comp.get('state')} hq={hq.get('state')}; rank winner={rank_winner or 'n/a'}.",
                rank_winner,
                rank_branch_rn,
                rank_hq_rn,
            )
        return (
            "HQ SWAP",
            "HQ SWAP (PROMOTE BRANCH)",
            "KEEP BK ON BRANCH (after promote)",
            "High",
            f"Branch address matches debtor ({branch_addr_score}) better than HQ ({hq_addr_score}); promote branch.",
            f"p_rank_sns_for_hq picked {rank_winner or 'n/a'} (rn {rank_hq_rn if rank_winner == hq_safe else rank_branch_rn}); address overrides rank for BK routing.",
            rank_winner,
            rank_branch_rn,
            rank_hq_rn,
        )

    if bk_on_branch and bk_on_hq and same_sos_strong(same_sos):
        return (
            "BK COPY",
            "NO GROUP CHANGE",
            "HIDE BRANCH BK; KEEP HQ BK; RECALC BRANCH",
            "High",
            "Same SOS/name cluster; BK on both branch and HQ — cleanup duplicate branch BK.",
            f"Oracle rank winner={rank_winner or 'n/a'}; address branch={branch_addr_score} hq={hq_addr_score}.",
            rank_winner,
            rank_branch_rn,
            rank_hq_rn,
        )

    if distinct_entity or (bk_on_branch and bk_on_hq and not same_sos_strong(same_sos) and branch_hq_score < 0.85):
        return (
            "HIGH ACTION",
            "SEPARATE + PROMOTE BRANCH TO HQ",
            "KEEP BK ON BRANCH (after promote)",
            "High",
            "Distinct legal entity vs HQ (SOS/name); promote branch, do not copy BK to old HQ.",
            f"Name score branch/HQ={branch_hq_score}; same SOS={same_sos}; rank winner={rank_winner or 'n/a'}.",
            rank_winner,
            rank_branch_rn,
            rank_hq_rn,
        )


    if hq_addr_score >= 0.7 and branch_addr_score < 0.55 and same_sos_strong(same_sos):
        if bk_on_branch and not bk_on_hq:
            return (
                "BK COPY",
                "NO GROUP CHANGE",
                "COPY BK TO HQ; HIDE BRANCH BK; RECALC BRANCH",
                "High",
                f"HQ address matches debtor ({hq_addr_score}) better than branch ({branch_addr_score}); copy BK to HQ.",
                f"Oracle rank winner={rank_winner or 'n/a'}; same SOS cluster supports HQ routing.",
                rank_winner,
                rank_branch_rn,
                rank_hq_rn,
            )

    if same_sos_strong(same_sos) and branch_hq_score >= 0.7:
        if valid_rank and rank_winner == hq_safe and hq_addr_score >= branch_addr_score:
            if bk_on_branch and not bk_on_hq:
                return (
                    "BK COPY",
                    "NO GROUP CHANGE",
                    "COPY BK TO HQ; HIDE BRANCH BK; RECALC BRANCH",
                    "High",
                    f"Same SOS/name; Oracle rank and address both favor HQ {hq_safe}.",
                    f"Address branch={branch_addr_score} hq={hq_addr_score}; rank branch rn={rank_branch_rn} hq rn={rank_hq_rn}.",
                    rank_winner,
                    rank_branch_rn,
                    rank_hq_rn,
                )
        if valid_rank and rank_winner == safe and branch_addr_score >= hq_addr_score - 0.1:
            return (
                "HQ SWAP",
                "HQ SWAP (PROMOTE BRANCH)",
                "KEEP BK ON BRANCH (after promote)",
                "High",
                f"Same SOS/name cluster but Oracle rank favors branch {safe} for HQ.",
                f"Address branch={branch_addr_score} hq={hq_addr_score}; rank branch rn={rank_branch_rn} hq rn={rank_hq_rn}.",
                rank_winner,
                rank_branch_rn,
                rank_hq_rn,
            )
        if bk_on_branch and not bk_on_hq and branch_addr_score > hq_addr_score:
            return (
                "HQ SWAP",
                "HQ SWAP (PROMOTE BRANCH)",
                "KEEP BK ON BRANCH (after promote)",
                "High",
                "Same SOS/name but branch address is closer to debtor than HQ.",
                f"Address delta={addr_delta}; rank winner={rank_winner or 'n/a'}.",
                rank_winner,
                rank_branch_rn,
                rank_hq_rn,
            )
        if bk_on_branch and not bk_on_hq:
            return (
                "BK COPY",
                "NO GROUP CHANGE",
                "COPY BK TO HQ; HIDE BRANCH BK; RECALC BRANCH",
                "Medium",
                f"Same SOS/name cluster; default copy-to-HQ when addresses are similar.",
                f"Address branch={branch_addr_score} hq={hq_addr_score}; rank winner={rank_winner or 'n/a'}.",
                rank_winner,
                rank_branch_rn,
                rank_hq_rn,
            )

    if same_sos_loose(same_sos) and branch_hq_score >= 0.85:
        if branch_addr_score >= hq_addr_score + 0.15:
            return (
                "HQ SWAP",
                "HQ SWAP (PROMOTE BRANCH)",
                "KEEP BK ON BRANCH (after promote)",
                "Medium",
                "Related SOS; branch address closer to debtor — favor promote over copy.",
                f"Address branch={branch_addr_score} hq={hq_addr_score}; rank winner={rank_winner or 'n/a'}.",
                rank_winner,
                rank_branch_rn,
                rank_hq_rn,
            )
        return (
            "REVIEW",
            "NO GROUP CHANGE",
            "REVIEW COPY TO HQ VS PROMOTE",
            "Medium",
            "Related SOS and similar names; confirm same legal entity and compare addresses before copy-to-HQ.",
            f"Address branch={branch_addr_score} hq={hq_addr_score}; rank winner={rank_winner or 'n/a'}.",
            rank_winner,
            rank_branch_rn,
            rank_hq_rn,
        )

    return (
        "HIGH ACTION",
        "SEPARATE + PROMOTE BRANCH TO HQ",
        "KEEP BK ON BRANCH (after promote)",
        "High",
        "Branch/HQ identity differs; promote branch to loc 1, do not copy BK to old HQ.",
        f"Address branch={branch_addr_score} hq={hq_addr_score}; rank winner={rank_winner or 'n/a'}.",
        rank_winner,
        rank_branch_rn,
        rank_hq_rn,
    )


def analyze_enrichment(data: dict) -> list[dict]:
    records = data["records"]
    qc: list[dict] = []
    seen_event: dict = {}
    by_case: dict[str, list] = defaultdict(list)
    by_cluster: dict = defaultdict(list)

    for idx, rec in enumerate(records, start=2):
        by_case[rec.get("alternate_case_number", "")].append((idx, rec))
        cluster_key = (
            rec.get("cust_court"),
            rec.get("filing_date"),
            rec.get("release_date"),
            norm(rec.get("defendant_address", "")),
            norm(rec.get("defendant_city", "")),
            rec.get("defendant_state"),
        )
        by_cluster[cluster_key].append((idx, rec))

    for idx, rec in enumerate(records, start=2):
        safe = rec["safe_number"]
        comp = first(data["company"].get(safe, []))
        rel = first(data["relationship"].get(safe, []))
        hq_safe = comp.get("hq_safe_number") or ""
        hq = first(data["hq"].get(hq_safe, [])) if hq_safe else {}
        bk_rows = data["bankruptcy"].get(rec.get("alternate_case_number", ""), [])
        score = name_score(rec.get("defendant_name", ""), rec.get("company_name", ""))
        comp_score = name_score(rec.get("defendant_name", ""), comp.get("company_name", rec.get("company_name", "")))
        flags: list[tuple[str, str, str]] = []

        event_key = (
            rec.get("defendant_rmsid"),
            rec.get("unique_case_id"),
            rec.get("alternate_case_number"),
            rec.get("filing_date"),
            rec.get("release_date"),
            rec.get("safe_number"),
        )
        if event_key in seen_event:
            flags.append(
                (
                    "MEDIUM",
                    "DUPLICATE_ROW",
                    f"Duplicate identical RMSID/case/event as source row {seen_event[event_key]}; import one copy only.",
                )
            )
        else:
            seen_event[event_key] = idx

        loc = str(comp.get("location_type") or rec.get("location_type") or "")
        if loc == "2":
            same_sos = data["same_sos"].get(safe, "")
            branch_hq_score = name_score(comp.get("company_name", ""), hq.get("company_name", ""))
            if same_sos_strong(same_sos) and branch_hq_score >= 0.7:
                sev = "MEDIUM"
                msg = "Auto match on branch; same-SOS/same-name HQ — likely copy BK to HQ or hide branch BK."
            elif same_sos_loose(same_sos) and branch_hq_score >= 0.85:
                sev = "MEDIUM"
                msg = "Auto match on branch; related-SOS and very similar HQ name — review copy-to-HQ vs promote."
            else:
                sev = "HIGH"
                msg = "Auto match on branch with uncertain/different HQ identity; review separation/promote-to-HQ."
            flags.append((sev, "BRANCH_BK_MATCH", msg))

        if score < 0.55 and comp_score < 0.55:
            flags.append(
                (
                    "HIGH",
                    "LOW_NAME_SIMILARITY",
                    f"Debtor/company name similarity is low ({score:.2f}); possible bad auto match or alias/DBA needing PACER.",
                )
            )
        elif score < 0.72 and loc != "2":
            flags.append(
                (
                    "MEDIUM",
                    "NAME_REVIEW",
                    f"Debtor/company name similarity is moderate ({score:.2f}); verify legal debtor vs DBA/alias.",
                )
            )

        active = active_bk(bk_rows)
        if active:
            active_safes = sorted({r.get("safe_number") for r in active if r.get("safe_number")})
            if safe not in active_safes:
                flags.append(
                    (
                        "HIGH",
                        "CASE_ALREADY_ON_DIFFERENT_SAFE",
                        f"Oracle bankruptcy already has this case on {', '.join(active_safes)}; matched SAFE is {safe}.",
                    )
                )
            elif rec.get("release_date"):
                if any(
                    r.get("release_date") == rec.get("release_date")
                    for r in active
                    if r.get("safe_number") == safe
                ):
                    flags.append(("MEDIUM", "EVENT_ALREADY_LOADED", "Release/event appears already loaded on same SAFE."))
                else:
                    flags.append(("LOW", "EXISTING_CASE_NEW_EVENT", "Initial case exists; release/event may need to be added."))
            else:
                flags.append(("MEDIUM", "CASE_ALREADY_LOADED", "Case appears already loaded; avoid duplicate import."))

        case_key = rec.get("alternate_case_number", "")
        if len(by_case[case_key]) > 1:
            safes = sorted({r["safe_number"] for _, r in by_case[case_key]})
            names = sorted({norm(r["defendant_name"]) for _, r in by_case[case_key]})
            if len(safes) > 1 or len(names) > 1:
                flags.append(
                    (
                        "MEDIUM",
                        "MULTI_ROW_CASE_FAMILY",
                        f"Same case in {len(by_case[case_key])} rows across {len(safes)} SAFE(s); review duplicates/legal debtor routing.",
                    )
                )

        cluster_key = (
            rec.get("cust_court"),
            rec.get("filing_date"),
            rec.get("release_date"),
            norm(rec.get("defendant_address", "")),
            norm(rec.get("defendant_city", "")),
            rec.get("defendant_state"),
        )
        cluster = by_cluster[cluster_key]
        cluster_names = {strip_suffix(r["defendant_name"]) for _, r in cluster}
        if len(cluster) >= 2 and len(cluster_names) >= 2:
            flags.append(
                (
                    "LOW",
                    "SAME_ADDRESS_CLUSTER",
                    f"{len(cluster)} same court/date/address rows; possible related debtor group for group-structure review.",
                )
            )

        for sev, flag, note in flags:
            qc.append(
                {
                    "source_row": idx,
                    "severity": sev,
                    "flag": flag,
                    "alternate_case_number": rec.get("alternate_case_number", ""),
                    "defendant_rmsid": rec.get("defendant_rmsid", ""),
                    "unique_case_id": rec.get("unique_case_id", ""),
                    "safe_number": safe,
                    "defendant_name": rec.get("defendant_name", ""),
                    "company_name": rec.get("company_name", ""),
                    "oracle_company_name": comp.get("company_name", ""),
                    "location_type": loc,
                    "branch_count": comp.get("cnt_br", ""),
                    "in_group_structure": comp.get("sn_in_grpstr", ""),
                    "corp_file_key": comp.get("corp_file_key", ""),
                    "hq_safe_number": hq_safe,
                    "hq_name": comp.get("hq_name", "") or hq.get("company_name", ""),
                    "hq_corp_file_key": hq.get("corp_file_key", ""),
                    "same_sos_chk": data["same_sos"].get(safe, ""),
                    "company_id": rel.get("companyid", ""),
                    "parent_company_id": rel.get("parentid", ""),
                    "filing_date": rec.get("filing_date", ""),
                    "release_date": rec.get("release_date", ""),
                    "name_score": round(score, 3),
                    "note": note,
                    "recommended_action": recommend_action(sev, flag, loc, safe, hq_safe),
                }
            )

    qc.sort(key=lambda r: (severity_rank(r["severity"]), r["source_row"], r["flag"]))
    return qc


def build_branch_action_rows(data: dict, qc_rows: list[dict]) -> list[dict]:
    records = data["records"]
    seen_rows: set[int] = set()
    branch_rows: list[dict] = []
    hq_ranks = data.get("hq_rank", {})

    for row in qc_rows:
        if row["flag"] != "BRANCH_BK_MATCH":
            continue
        src = row["source_row"]
        if src in seen_rows:
            continue
        seen_rows.add(src)
        rec = records[src - 2]
        comp = first(data["company"].get(rec["safe_number"], []))
        hq_safe = comp.get("hq_safe_number") or ""
        hq = first(data["hq"].get(hq_safe, [])) if hq_safe else {}
        bk_rows = data["bankruptcy"].get(rec.get("alternate_case_number", ""), [])
        same_sos = str(data["same_sos"].get(rec["safe_number"], ""))
        branch_hq_score = round(name_score(comp.get("company_name", ""), hq.get("company_name", "")), 3)
        branch_addr_score = address_match_score(defendant_address_parts(rec), company_address_parts(comp))
        hq_addr_score = address_match_score(defendant_address_parts(rec), company_address_parts(hq))
        rank_rows = hq_ranks.get(rec.get("alternate_case_number", ""), [])
        (
            status,
            group_action,
            bk_action,
            confidence,
            evidence,
            final_reason,
            rank_winner,
            rank_branch_rn,
            rank_hq_rn,
        ) = classify_branch_actions(
            rec,
            comp,
            hq,
            bk_rows,
            same_sos,
            branch_hq_score,
            rank_rows,
            branch_addr_score,
            hq_addr_score,
        )
        addr_match_safe = rec["safe_number"] if branch_addr_score >= hq_addr_score else hq_safe
        if group_action.startswith("HQ SWAP") or group_action.startswith("SEPARATE"):
            target_safe = rec["safe_number"]
            target_name = comp.get("company_name", rec.get("company_name", ""))
        elif group_action == "NO GROUP CHANGE":
            target_safe = hq_safe
            target_name = hq.get("company_name", "")
        else:
            target_safe = hq_safe or rec["safe_number"]
            target_name = hq.get("company_name", "") or comp.get("company_name", "")

        branch_rows.append(
            {
                "source_row": src,
                "alternate_case_number": rec.get("alternate_case_number", ""),
                "defendant_name": rec.get("defendant_name", ""),
                "status": status,
                "group_action": group_action,
                "bankruptcy_action": bk_action,
                "branch_safe_number": rec["safe_number"],
                "branch_name": comp.get("company_name", rec.get("company_name", "")),
                "current_hq_safe_number": hq_safe,
                "current_hq_name": comp.get("hq_name", "") or hq.get("company_name", ""),
                "target_safe_number": target_safe,
                "target_name": target_name,
                "branch_state": comp.get("state", ""),
                "hq_state": hq.get("state", ""),
                "same_sos_chk": same_sos,
                "name_score_branch_hq": branch_hq_score,
                "address_score_branch": branch_addr_score,
                "address_score_hq": hq_addr_score,
                "address_match_safe": addr_match_safe,
                "rank_winner_safe": rank_winner,
                "rank_branch_rn": rank_branch_rn,
                "rank_hq_rn": rank_hq_rn,
                "filing_date": rec.get("filing_date", ""),
                "release_date": rec.get("release_date", ""),
                "confidence": confidence,
                "evidence": evidence,
                "final_reason": final_reason,
                "caution_or_next_step": row["recommended_action"],
            }
        )
    return branch_rows


def qc_fill(severity: str, flag: str) -> PatternFill:
    if severity == "HIGH":
        return PatternFill("solid", fgColor=RED)
    if severity == "MEDIUM":
        return PatternFill("solid", fgColor=YELLOW)
    if flag == "SAME_ADDRESS_CLUSTER":
        return PatternFill("solid", fgColor=BLUE)
    return PatternFill("solid", fgColor=GREEN)


def branch_fill(status: str) -> PatternFill:
    if status == "BK COPY":
        return PatternFill("solid", fgColor=BK_COPY)
    if status in {"HIGH ACTION", "HQ SWAP"}:
        return PatternFill("solid", fgColor=HIGH_ACTION)
    return PatternFill("solid", fgColor=YELLOW)


def style_sheet(ws, header_count: int, widths: dict[str, float] | None = None) -> None:
    ws.freeze_panes = "A2"
    if ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = ws.dimensions
    header_fill = PatternFill("solid", fgColor=NAVY)
    side = Side(style="thin", color=LINE)
    for row in ws.iter_rows():
        for cell in row:
            cell.font = Font(name="Aptos Narrow", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(left=side, right=side, top=side, bottom=side)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = Font(name="Aptos Narrow", size=10, bold=True, color=WHITE)
    if widths:
        for col, width in widths.items():
            ws.column_dimensions[col].width = width


def append_qc_sheet(ws, rows: list[dict]) -> None:
    ws.append(QC_HEADERS)
    for row in rows:
        ws.append([row.get(h, "") for h in QC_HEADERS])
        fill = qc_fill(row["severity"], row["flag"])
        for cell in ws[ws.max_row]:
            cell.fill = fill
    style_sheet(
        ws,
        len(QC_HEADERS),
        {
            "A": 10, "B": 11, "C": 24, "D": 42, "E": 16, "F": 16, "G": 18,
            "H": 16, "I": 36, "J": 34, "K": 34, "L": 11, "M": 11, "N": 11,
            "O": 18, "P": 16, "Q": 34, "R": 18, "S": 14, "T": 18, "U": 18,
            "V": 13, "W": 13, "X": 11, "Y": 70,
        },
    )


def append_branch_sheet(ws, rows: list[dict]) -> None:
    ws.append(BRANCH_HEADERS)
    for row in rows:
        ws.append([row.get(h, "") for h in BRANCH_HEADERS])
        fill = branch_fill(row["status"])
        for cell in ws[ws.max_row]:
            cell.fill = fill
    style_sheet(ws, len(BRANCH_HEADERS))


def build_workbooks(
    source: Path,
    enrichment: dict,
    qc_rows: list[dict],
    branch_rows: list[dict],
    out_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    with source.open(newline="", encoding="utf-8-sig") as handle:
        source_rows = list(csv.DictReader(handle))

    review_path = out_dir / f"{stem}_qc_review.xlsx"
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["metric", "value"])
    summary.append(["source_file", str(source)])
    summary.append(["auto_match_rows", len(source_rows)])
    summary.append(["qc_rows", len(qc_rows)])
    summary.append(["branch_loc2_rows", len(branch_rows)])
    for sev, count in Counter(r["severity"] for r in qc_rows).items():
        summary.append([f"severity_{sev}", count])
    for flag, count in Counter(r["flag"] for r in qc_rows).items():
        summary.append([f"flag_{flag}", count])
    style_sheet(summary, 2)
    summary.column_dimensions["A"].width = 34
    summary.column_dimensions["B"].width = 20

    ws = wb.create_sheet("Action Queue")
    append_qc_sheet(ws, [r for r in qc_rows if r["severity"] in {"HIGH", "MEDIUM"}])

    branch = wb.create_sheet("Branch HQ")
    append_qc_sheet(branch, [r for r in qc_rows if r["flag"] == "BRANCH_BK_MATCH"])

    existing = wb.create_sheet("Existing Case Conflicts")
    append_qc_sheet(
        existing,
        [
            r
            for r in qc_rows
            if r["flag"]
            in {
                "CASE_ALREADY_ON_DIFFERENT_SAFE",
                "EVENT_ALREADY_LOADED",
                "CASE_ALREADY_LOADED",
                "EXISTING_CASE_NEW_EVENT",
            }
        ],
    )

    clusters = wb.create_sheet("Related Clusters")
    append_qc_sheet(
        clusters,
        [r for r in qc_rows if r["flag"] in {"MULTI_ROW_CASE_FAMILY", "SAME_ADDRESS_CLUSTER"}],
    )

    raw = wb.create_sheet("Raw Auto Matches")
    headers = list(source_rows[0].keys()) if source_rows else []
    raw.append(headers)
    for row in source_rows:
        raw.append([row.get(h, "") for h in headers])
    style_sheet(raw, len(headers))

    wb.save(review_path)

    branch_path = out_dir / f"{stem}_branch_actions.xlsx"
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.title = "Branch Actions"
    append_branch_sheet(ws2, branch_rows)
    summary_sheet = wb2.create_sheet("Summary", 0)
    summary_sheet.append(["metric", "value"])
    summary_sheet.append(["branch_loc2_reviewed", len(branch_rows)])
    summary_sheet.append(["separate_promote", sum(1 for r in branch_rows if r["group_action"].startswith("SEPARATE"))])
    summary_sheet.append(["hq_swap", sum(1 for r in branch_rows if "HQ SWAP" in r["group_action"])])
    summary_sheet.append(["copy_to_hq", sum(1 for r in branch_rows if "COPY BK TO HQ" in r["bankruptcy_action"])])
    summary_sheet.append(["hide_branch_keep_hq", sum(1 for r in branch_rows if "KEEP HQ BK" in r["bankruptcy_action"])])
    style_sheet(summary_sheet, 2)
    wb2.save(branch_path)

    return review_path, branch_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-matches QC pipeline.")
    parser.add_argument("--input", type=Path, help="Local auto_matches CSV.")
    parser.add_argument("--s3-uri", help="Full S3 URI to CSV.")
    parser.add_argument("--s3-prefix", default=DEFAULT_S3_PREFIX, help="S3 folder prefix.")
    parser.add_argument("--date", help="Date stamp YYYYMMDD (default: today).")
    parser.add_argument("--aws-profile", default="<AWS_PROFILE>")
    parser.add_argument("--output-dir", type=Path, help="Output directory (default work/YYYY-MM-DD).")
    parser.add_argument("--skip-enrich", action="store_true", help="Reuse existing enrichment JSON.")
    parser.add_argument("--skip-rank", action="store_true", help="Skip p_rank_sns_for_hq Oracle calls.")
    args = parser.parse_args()

    out_dir = args.output_dir or (ROOT / "work" / date.today().isoformat())
    out_dir.mkdir(parents=True, exist_ok=True)

    source = resolve_input_path(args, out_dir) if not args.input else Path(args.input)
    stem = source.stem
    enrich_path = out_dir / f"{stem}_enrichment.json"
    analysis_path = out_dir / f"{stem}_qc_analysis.json"

    if args.skip_enrich and enrich_path.exists():
        enrichment = json.loads(enrich_path.read_text(encoding="utf-8"))
        print(f"Reused {enrich_path}")
    else:
        with source.open(newline="", encoding="utf-8-sig") as handle:
            records = list(csv.DictReader(handle))
        print(f"Loaded {len(records)} auto-match rows from {source}")
        enrichment = enrich_records(records)

    if not args.skip_rank:
        enrichment["hq_rank"] = enrich_hq_ranks(
            enrichment["records"], enrichment["company"], skip_rank=False
        )

    if not args.skip_enrich or not args.skip_rank:
        enrich_path.write_text(json.dumps(enrichment, indent=2), encoding="utf-8")
        print(f"Wrote {enrich_path}")

    qc_rows = analyze_enrichment(enrichment)
    branch_rows = build_branch_action_rows(enrichment, qc_rows)
    analysis_path.write_text(
        json.dumps(
            {
                "qc_rows": qc_rows,
                "branch_rows": branch_rows,
                "meta": enrichment["meta"],
                "counts": dict(Counter(r["flag"] for r in qc_rows)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {analysis_path}")

    review_path, branch_path = build_workbooks(source, enrichment, qc_rows, branch_rows, out_dir, stem)
    print(f"Wrote {review_path}")
    print(f"Wrote {branch_path}")
    print(
        json.dumps(
            {
                "rows": enrichment["meta"]["rows"],
                "qc_rows": len(qc_rows),
                "branch_loc2": len(branch_rows),
                "severity": dict(Counter(r["severity"] for r in qc_rows)),
                "flags": dict(Counter(r["flag"] for r in qc_rows)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
