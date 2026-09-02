#!/usr/bin/env python3
"""PACER Authentication + PCL Case Locator API client.

Env vars (never printed):
  PACER_USERNAME / PACER_PASSWORD  required
  PACER_ENV                        qa | prod (default: prod)
  PACER_CLIENT_CODE                optional; required by some accounts for search
  PACER_OTP / PACER_OTP_SECRET     optional MFA one-shot code or TOTP secret

BK-oriented usage:
   python scripts/pacer_api.py lookup --alternate-case <ALTERNATE_CASE> --cust-court <COURT_CODE> --i-understand-billing

Docs:
  https://pacer.uscourts.gov/file-case/developer-resources
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENVS = {
    "qa": {
        "auth": "https://qa-login.uscourts.gov",
        "pcl": "https://qa-pcl.uscourts.gov",
        "register": "https://qa-pacer.uscourts.gov",
    },
    "prod": {
        "auth": "https://pacer.login.uscourts.gov",
        "pcl": "https://pcl.uscourts.gov",
        "register": "https://pacer.uscourts.gov",
    },
}

# Data Operations cust_court district token -> PACER district letter (e.g. NOR -> n)
_DISTRICT_TOKEN = {
    "CEN": "c",
    "CENT": "c",
    "EAS": "e",
    "EAST": "e",
    "NOR": "n",
    "NORT": "n",
    "SOU": "s",
    "SOUT": "s",
    "MID": "m",
    "MIDD": "m",
    "WES": "w",
    "WEST": "w",
}

# States with a single bankruptcy court (no N/S/E/W/M letter)
_SINGLE_DISTRICT = {
    "AK", "AZ", "CO", "CT", "DC", "DE", "GU", "HI", "ID", "KS", "MA", "MD",
    "ME", "MN", "MT", "ND", "NE", "NH", "NJ", "NM", "NV", "OR", "PR", "RI",
    "SC", "SD", "UT", "VI", "VT", "WY",
}

_ENTITY_RE = re.compile(
    r"\b("
    r"INC\.?|INCORPORATED|LLC|L\.?L\.?C\.?|CORP\.?|CORPORATION|LTD\.?|LIMITED|"
    r"L\.?P\.?|LLP|L\.?L\.?P\.?|PLC|CO\.|COMPANY|COMPANIES|TRUST|PARTNERSHIP|"
    r"PC|P\.C\.|PLLC|P\.L\.L\.C\.|ASSOCIATES|HOLDINGS|GROUP|BANK|CREDIT UNION"
    r")\b",
    re.I,
)


def alternate_case_to_pacer(value: str) -> str:
    """Convert an eight-digit alternate case value to the court-search form."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 4:
        return str(value or "")
    year, rest = digits[:2], digits[2:]
    if rest.startswith("0") and len(rest) > 1:
        rest = rest[1:]
    return f"{year}-{rest}"


def cust_court_to_pacer(cust_court: str) -> str | None:
    """Map Data Operations cust_court (e.g. TXNORF8, CACENF1) to PACER courtId (txnbk, cacbk)."""
    raw = (cust_court or "").strip()
    if not raw:
        return None
    code = raw.upper()

    # Already a PACER id
    low = raw.lower()
    if re.fullmatch(r"[a-z]{2,5}bk", low):
        return low
    if re.fullmatch(r"[a-z]{2,6}", low) and low.endswith(("bk", "dc", "ca")):
        return low

    # Strip trailing office: F1 / 1 / F12
    base = re.sub(r"F?\d+$", "", code)
    if len(base) < 2:
        return None

    state = base[:2]
    rest = base[2:]

    if state in _SINGLE_DISTRICT and not rest:
        return f"{state.lower()}bk"

    # Try longest district token first
    for token_len in (4, 3):
        if len(rest) >= token_len:
            token = rest[:token_len]
            letter = _DISTRICT_TOKEN.get(token)
            if letter:
                return f"{state.lower()}{letter}bk"

    if state in _SINGLE_DISTRICT:
        return f"{state.lower()}bk"
    return None


def classify_title(title: str) -> str:
    if _ENTITY_RE.search(title or ""):
        return "business"
    return "person_or_other"


def summarize_hits(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for c in content or []:
        title = (c.get("caseTitle") or "").strip()
        rows.append(
            {
                "courtId": c.get("courtId"),
                "caseNumberFull": c.get("caseNumberFull"),
                "caseType": c.get("caseType"),
                "chapter": c.get("bankruptcyChapter") or "",
                "title": title,
                "title_class": classify_title(title),
                "dateFiled": c.get("dateFiled"),
                "dateDischarged": c.get("dateDischarged") or "",
                "dateDismissed": c.get("dateDismissed") or "",
                "disposition": c.get("dispositionMethod") or "",
                "caseLink": c.get("caseLink"),
            }
        )
    return rows


def _env_name(cli_env: str | None) -> str:
    name = (cli_env or os.environ.get("PACER_ENV") or "prod").strip().lower()
    if name not in ENVS:
        raise SystemExit(f"Unknown PACER_ENV={name!r}; use qa or prod")
    return name


def _credentials() -> tuple[str, str]:
    user = os.environ.get("PACER_USERNAME", "").strip()
    password = os.environ.get("PACER_PASSWORD", "")
    if not user or not password:
        raise SystemExit(
            "Set PACER_USERNAME and PACER_PASSWORD in the environment "
            "(user-level env vars are fine)."
        )
    return user, password


def _otp_code(cli_otp: str | None) -> str | None:
    if cli_otp:
        return cli_otp.strip()
    one_shot = os.environ.get("PACER_OTP", "").strip()
    if one_shot:
        return one_shot
    secret = os.environ.get("PACER_OTP_SECRET", "").strip()
    if not secret:
        return None
    try:
        import pyotp  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "PACER_OTP_SECRET is set but pyotp is not installed. "
            "Run: pip install pyotp"
        ) from exc
    return pyotp.TOTP(secret).now()


def _http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, dict[str, str], Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {
        "Accept": "application/json",
        "User-Agent": "data-operations-workspace-pacer-api/1.1",
    }
    if payload is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)
    req = Request(url, data=body, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            resp_headers = {k: v for k, v in resp.headers.items()}
            data: Any = json.loads(raw) if raw.strip() else {}
            return resp.status, resp_headers, data
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw.strip() else {"raw": raw}
        except json.JSONDecodeError:
            data = {"raw": raw}
        return exc.code, {k: v for k, v in exc.headers.items()}, data
    except URLError as exc:
        raise SystemExit(f"Network error calling {url}: {exc}") from exc


def authenticate(
    env: str,
    *,
    client_code: str | None = None,
    otp: str | None = None,
) -> dict[str, Any]:
    login_id, password = _credentials()
    urls = ENVS[env]
    payload: dict[str, Any] = {
        "loginId": login_id,
        "password": password,
        "redactFlag": "1",
    }
    code = client_code if client_code is not None else os.environ.get("PACER_CLIENT_CODE")
    if code:
        payload["clientCode"] = code
    otp_code = _otp_code(otp)
    if otp_code:
        payload["otpCode"] = otp_code

    status, headers, data = _http_json(
        "POST",
        f"{urls['auth']}/services/cso-auth",
        payload,
    )
    token = None
    if isinstance(data, dict):
        token = data.get("nextGenCSO") or data.get("token")
    if not token:
        token = headers.get("X-NEXT-GEN-CSO") or headers.get("x-next-gen-cso")

    ok = status == 200 and bool(token)
    safe_response: dict[str, Any] = {}
    for k, v in (data or {}).items():
        key = str(k).lower()
        if key in {"password", "nextgencso", "token", "otpcode"}:
            safe_response[k] = "<redacted>" if v else v
        else:
            safe_response[k] = v
    return {
        "ok": ok,
        "env": env,
        "status": status,
        "login_id": login_id,
        "token_present": bool(token),
        "token_prefix": (token[:8] + "...") if token else None,
        "token": token,
        "response": safe_response,
        "register_url": urls["register"],
    }


def logout(env: str, token: str) -> dict[str, Any]:
    urls = ENVS[env]
    status, _, data = _http_json(
        "POST",
        f"{urls['auth']}/services/cso-logout",
        {"nextGenCSO": token},
        headers={"X-NEXT-GEN-CSO": token},
    )
    return {"ok": status == 200, "status": status, "response": data}


def find_cases(
    env: str,
    token: str,
    *,
    case_number: str | None = None,
    court_id: str | None = None,
    jurisdiction_type: str | None = None,
    page: int = 0,
) -> dict[str, Any]:
    urls = ENVS[env]
    query: dict[str, Any] = {}
    if case_number:
        # PCL accepts yy-nnnnn via caseNumberFull (string).
        # Do not send hyphenated values as caseNumber — that field is numeric.
        query["caseNumberFull"] = case_number
    if court_id:
        query["courtId"] = [court_id] if isinstance(court_id, str) else court_id
    if jurisdiction_type:
        query["jurisdictionType"] = jurisdiction_type

    status, headers, data = _http_json(
        "POST",
        f"{urls['pcl']}/pcl-public-api/rest/cases/find?{urlencode({'page': page})}",
        query,
        headers={"X-NEXT-GEN-CSO": token},
    )
    new_token = headers.get("X-NEXT-GEN-CSO") or headers.get("x-next-gen-cso") or token
    return {
        "ok": status == 200,
        "status": status,
        "token": new_token,
        "request": query,
        "response": data,
    }


def resolve_court_id(
    *,
    court_id: str | None = None,
    cust_court: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (pacer_court_id, mapping_note)."""
    if court_id:
        return court_id.lower().strip(), "explicit --court-id"
    if cust_court:
        mapped = cust_court_to_pacer(cust_court)
        if mapped:
            return mapped, f"mapped cust_court={cust_court} -> {mapped}"
        return None, f"could not map cust_court={cust_court}"
    return None, "no court filter"


def _require_billing_ok(env: str, flag: bool, token: str) -> bool:
    if env == "prod" and not flag:
        print(
            "Refusing production search without --i-understand-billing "
            "(PCL searches are billable). Auth-only succeeded.",
            file=sys.stderr,
        )
        logout(env, token)
        return False
    return True


def cmd_setup_check(args: argparse.Namespace) -> int:
    env = _env_name(args.env)
    user = os.environ.get("PACER_USERNAME", "")
    password = os.environ.get("PACER_PASSWORD", "")
    print("PACER API setup check")
    print(f"  env            : {env}")
    print(f"  auth URL       : {ENVS[env]['auth']}/services/cso-auth")
    print(f"  pcl URL        : {ENVS[env]['pcl']}/pcl-public-api/rest")
    print(f"  PACER_USERNAME : {'present' if user else 'MISSING'}")
    print(f"  PACER_PASSWORD : {'present' if password else 'MISSING'}")
    print(f"  PACER_CLIENT_CODE : {'present' if os.environ.get('PACER_CLIENT_CODE') else 'not set'}")
    print(
        f"  PACER_OTP/SECRET  : "
        f"{'present' if (os.environ.get('PACER_OTP') or os.environ.get('PACER_OTP_SECRET')) else 'not set'}"
    )
    if env == "qa":
        print(f"  QA register    : {ENVS['qa']['register']}")
        print("  Note: QA needs a separate account from production.")
    else:
        print("  Note: Production PCL searches are billable.")
    return 0 if user and password else 1


def cmd_auth(args: argparse.Namespace) -> int:
    env = _env_name(args.env)
    result = authenticate(env, client_code=args.client_code, otp=args.otp)
    safe = {k: v for k, v in result.items() if k != "token"}
    print(json.dumps(safe, indent=2, default=str))
    if not result["ok"]:
        print(
            "\nAuth failed. If MFA is enabled, pass --otp <code> or set PACER_OTP. "
            "If the account requires a client code, set PACER_CLIENT_CODE.",
            file=sys.stderr,
        )
        return 1
    print("\nAuth OK — token received (not printed in full).", file=sys.stderr)
    if args.print_token:
        print(result["token"])
    return 0


def cmd_case(args: argparse.Namespace) -> int:
    env = _env_name(args.env)
    case_number = args.case_number
    if args.alternate_case:
        case_number = alternate_case_to_pacer(args.alternate_case)

    court_id, court_note = resolve_court_id(
        court_id=args.court_id,
        cust_court=getattr(args, "cust_court", None),
    )
    if getattr(args, "cust_court", None) and not court_id:
        print(json.dumps({"ok": False, "error": court_note}, indent=2))
        return 1

    auth = authenticate(env, client_code=args.client_code, otp=args.otp)
    if not auth["ok"]:
        print(json.dumps({k: v for k, v in auth.items() if k != "token"}, indent=2, default=str))
        return 1
    if not _require_billing_ok(env, args.i_understand_billing, auth["token"]):
        return 2

    jurisdiction = args.jurisdiction_type
    if jurisdiction is None and args.alternate_case:
        jurisdiction = "Bankruptcy"

    result = find_cases(
        env,
        auth["token"],
        case_number=case_number,
        court_id=court_id,
        jurisdiction_type=jurisdiction,
        page=args.page,
    )
    logout(env, result.get("token") or auth["token"])
    out = {
        "ok": result["ok"],
        "env": env,
        "status": result["status"],
        "court_note": court_note,
        "request": result["request"],
        "response": result["response"],
    }
    print(json.dumps(out, indent=2, default=str))
    return 0 if result["ok"] else 1


def cmd_lookup(args: argparse.Namespace) -> int:
    """BK review helper: court-scoped case lookup with compact summary."""
    env = _env_name(args.env)
    case_number = alternate_case_to_pacer(args.alternate_case)
    court_id, court_note = resolve_court_id(
        court_id=args.court_id,
        cust_court=args.cust_court,
    )

    if not court_id and not args.allow_all_courts:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "Court filter required for lookup. Pass --cust-court or --court-id, "
                        "or --allow-all-courts (nationwide; often many hits)."
                    ),
                    "court_note": court_note,
                    "alternate_case": args.alternate_case,
                    "pacer_case": case_number,
                },
                indent=2,
            )
        )
        return 1

    if args.cust_court and not court_id and not args.allow_all_courts:
        print(json.dumps({"ok": False, "error": court_note}, indent=2))
        return 1

    auth = authenticate(env, client_code=args.client_code, otp=args.otp)
    if not auth["ok"]:
        print(json.dumps({k: v for k, v in auth.items() if k != "token"}, indent=2, default=str))
        return 1
    if not _require_billing_ok(env, args.i_understand_billing, auth["token"]):
        return 2

    result = find_cases(
        env,
        auth["token"],
        case_number=case_number,
        court_id=court_id,
        jurisdiction_type=args.jurisdiction_type or "Bankruptcy",
        page=args.page,
    )
    logout(env, result.get("token") or auth["token"])

    resp = result.get("response") or {}
    content = resp.get("content") or []
    hits = summarize_hits(content)
    business = [h for h in hits if h["title_class"] == "business"]
    receipt = resp.get("receipt") or {}

    out = {
        "ok": result["ok"],
        "env": env,
        "status": result["status"],
        "alternate_case": args.alternate_case,
        "pacer_case": case_number,
        "cust_court": args.cust_court,
        "court_id": court_id,
        "court_note": court_note,
        "billable_pages": receipt.get("billablePages"),
        "search_fee": receipt.get("searchFee"),
        "hit_count": len(hits),
        "business_hit_count": len(business),
        "business_hits": business,
        "hits": hits,
        "request": result["request"],
    }

    if args.save:
        day = date.today().isoformat()
        out_dir = Path(__file__).resolve().parents[1] / "work" / day
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_case = re.sub(r"\W+", "_", args.alternate_case)
        court_part = court_id or "all"
        path = out_dir / f"pacer_lookup_{safe_case}_{court_part}.json"
        path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        out["saved_to"] = str(path)

    print(json.dumps(out, indent=2, default=str))
    if result["ok"] and not court_id and len(hits) > 3:
        print(
            f"\nNote: {len(hits)} nationwide hits — prefer --cust-court / --court-id next time.",
            file=sys.stderr,
        )
    return 0 if result["ok"] else 1


def cmd_convert(args: argparse.Namespace) -> int:
    for value in args.alternate_case:
        print(f"{value}\t{alternate_case_to_pacer(value)}")
    return 0


def cmd_map_court(args: argparse.Namespace) -> int:
    for value in args.cust_court:
        mapped = cust_court_to_pacer(value)
        print(f"{value}\t{mapped or 'UNMAPPED'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PACER Auth + PCL API helper")
    env = argparse.ArgumentParser(add_help=False)
    env.add_argument("--env", choices=["qa", "prod"], help="Override PACER_ENV")
    billing = argparse.ArgumentParser(add_help=False)
    billing.add_argument(
        "--i-understand-billing",
        action="store_true",
        help="Required for production searches (billable)",
    )
    auth_opts = argparse.ArgumentParser(add_help=False)
    auth_opts.add_argument("--otp", help="MFA one-time code")
    auth_opts.add_argument("--client-code", help="PACER client code")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser(
        "setup-check",
        parents=[env],
        help="Show env/config status (no network)",
    )
    c.set_defaults(func=cmd_setup_check)

    a = sub.add_parser(
        "auth",
        parents=[env, auth_opts],
        help="Authenticate and verify token (no search charge)",
    )
    a.add_argument(
        "--print-token",
        action="store_true",
        help="Print full token to stdout (sensitive)",
    )
    a.set_defaults(func=cmd_auth)

    s = sub.add_parser(
        "case",
        parents=[env, auth_opts, billing],
        help="Auth + case search (raw API response)",
    )
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--case-number", help="PACER case number, e.g. 26-11736")
    g.add_argument("--alternate-case", help="Eight-digit bankruptcy alternate_case")
    s.add_argument("--court-id", help="PACER court id, e.g. txnbk")
    s.add_argument("--cust-court", help="Data Operations cust_court, e.g. TXNORF8")
    s.add_argument(
        "--jurisdiction-type",
        choices=["Bankruptcy", "Civil", "Criminal", "Appellate"],
        help="Optional jurisdiction filter (default Bankruptcy when --alternate-case)",
    )
    s.add_argument("--page", type=int, default=0)
    s.set_defaults(func=cmd_case)

    lu = sub.add_parser(
        "lookup",
        parents=[env, auth_opts, billing],
        help="BK review lookup: court-scoped case search + compact summary",
    )
    lu.add_argument("--alternate-case", required=True, help="Eight-digit bankruptcy alternate_case")
    lu.add_argument("--cust-court", help="Data Operations cust_court, e.g. TXNORF8")
    lu.add_argument("--court-id", help="PACER court id override, e.g. txnbk")
    lu.add_argument(
        "--allow-all-courts",
        action="store_true",
        help="Allow nationwide search without court filter",
    )
    lu.add_argument(
        "--jurisdiction-type",
        choices=["Bankruptcy", "Civil", "Criminal", "Appellate"],
        default="Bankruptcy",
    )
    lu.add_argument("--page", type=int, default=0)
    lu.add_argument(
        "--save",
        action="store_true",
        help="Write JSON under work/YYYY-MM-DD/",
    )
    lu.set_defaults(func=cmd_lookup)

    x = sub.add_parser(
        "convert",
        parents=[env],
        help="Convert alternate_case values to PACER format",
    )
    x.add_argument("alternate_case", nargs="+")
    x.set_defaults(func=cmd_convert)

    m = sub.add_parser(
        "map-court",
        parents=[env],
        help="Map Data Operations cust_court codes to PACER courtId",
    )
    m.add_argument("cust_court", nargs="+")
    m.set_defaults(func=cmd_map_court)
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
