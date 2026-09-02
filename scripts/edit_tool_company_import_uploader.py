#!/usr/bin/env python
r"""
Upload Edit Tool company import workbooks (same endpoint as Company Import UI).

Pattern mirrors work/det_import_uploader.py: form scrape, session POST, message extract.

Dry run:
  python scripts\edit_tool_company_import_uploader.py C:\path\company_import.xlsx

Submit and poll grid + Oracle ~45s:
  python scripts\edit_tool_company_import_uploader.py C:\path\company_import.xlsx --submit --match "ROGUE FARE MEDFORD"

Auth uses logged-in Chrome CDP cookies (ASP.NET_SessionId on <EDIT_TOOL_HOST>).
Optional env:
  EDIT_TOOL_BASE_URL (default http://<EDIT_TOOL_HOST>)
  EDIT_TOOL_EMAIL (default <USERNAME>@<COMPANY_DOMAIN>)
  EDIT_TOOL_CDP_URL (default http://127.0.0.1:9222)
"""

from __future__ import annotations

import argparse
import html.parser
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

DEFAULT_BASE = os.environ.get("EDIT_TOOL_BASE_URL", "http://<EDIT_TOOL_HOST>")
IMPORT_PAGE = "/web/EditToolLive/Company/Import"
GRID_PAGE = "/web/EditToolLive/Company/ImportedCompaniesGrid"
DEFAULT_EMAIL = os.environ.get("EDIT_TOOL_EMAIL", "<USERNAME>@<COMPANY_DOMAIN>")
DEFAULT_CDP = os.environ.get("EDIT_TOOL_CDP_URL", "http://127.0.0.1:9222")


class FormParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, object]] = []
        self._form: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): v or "" for k, v in attrs}
        if tag.lower() == "form":
            self._form = {
                "action": attr.get("action", ""),
                "method": attr.get("method", "get"),
                "fields": {},
            }
            return
        if self._form is None or tag.lower() not in {"input", "button", "textarea", "select"}:
            return
        name = attr.get("name")
        if not name:
            return
        fields = self._form["fields"]
        assert isinstance(fields, dict)
        if tag.lower() == "textarea":
            fields[name] = ""
        else:
            fields[name] = attr.get("value", "")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None


def parse_forms(text: str) -> list[dict[str, object]]:
    parser = FormParser()
    parser.feed(text)
    return parser.forms


def extract_messages(text: str) -> list[str]:
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    words = (
        "import started",
        "success",
        "imported",
        "records",
        "error",
        "failed",
        "invalid",
        "denied",
        "email upon completion",
    )
    hits = [line for line in lines if line and any(word in line.lower() for word in words)]
    return hits[:20]


def parse_grid_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for block in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", block, flags=re.I | re.S)
        if not cells:
            continue
        cleaned = [re.sub(r"<[^>]+>", "", cell).strip() for cell in cells]
        if cleaned[0].lower() == "safenumber":
            continue
        if len(cleaned) >= 7:
            rows.append(
                {
                    "safe_number": cleaned[0],
                    "company_name": cleaned[1],
                    "address": cleaned[2],
                    "city": cleaned[3],
                    "state": cleaned[4],
                    "zip": cleaned[5],
                    "import_date": cleaned[6],
                }
            )
    return rows


def cookies_from_chrome(cdp_url: str, base_url: str, timeout: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    import_url = urljoin(base_url, IMPORT_PAGE)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("No browser contexts found on CDP endpoint.")
        context = browser.contexts[0]
        page = next(
            (pg for pg in context.pages if "EditToolLive/Company/Import" in pg.url),
            None,
        )
        if page is None:
            page = context.new_page()
            page.goto(import_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        page.bring_to_front()
        page.goto(import_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        page.wait_for_timeout(1500)
        if "Import Company" not in page.inner_text("body"):
            raise RuntimeError("Edit Tool import page not authenticated in Chrome.")
        return context.cookies([base_url, import_url])


def apply_cookies(session, cookies: list[dict]) -> None:
    for cookie in cookies:
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )


def form_data_for_import_page(session, base_url: str, timeout: int, email: str) -> dict[str, str]:
    import_url = urljoin(base_url, IMPORT_PAGE)
    page = session.get(import_url, timeout=timeout)
    page.raise_for_status()
    if "Import Company" not in page.text:
        raise RuntimeError("Import page fetch did not look authenticated.")

    for form in parse_forms(page.text):
        fields = dict(form.get("fields", {}))
        if "ImportFile" in fields or "Email" in fields:
            fields.pop("ImportFile", None)
            if email:
                fields["Email"] = email
            return {k: str(v) for k, v in fields.items()}
    return {"Email": email}


def oracle_lookup(company_name: str, timeout: int = 30) -> list[dict[str, str]]:
    script = Path(__file__).resolve().parent / "oracle_query.py"
    if not script.exists():
        return []

    import subprocess

    needle = company_name.strip().upper()
    if not needle:
        return []
    sql = (
        "SELECT safe_number, company_name, address, city, state, zip "
        "FROM company_search_view "
        f"WHERE location_type = 1 AND company_name LIKE '{needle}%' "
        "ORDER BY company_name"
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "-q", sql],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print("Oracle poll timed out; continuing grid poll.", file=sys.stderr)
        return []
    if proc.returncode != 0:
        print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
        return []

    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    headers = [h.strip() for h in lines[0].split(",")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        values = [v.strip() for v in line.split(",")]
        if len(values) == len(headers):
            rows.append(dict(zip(headers, values)))
    return rows


def poll_for_match(
    session,
    grid_url: str,
    match: str,
    poll_seconds: int,
    poll_interval: int,
    timeout: int,
    poll_oracle: bool,
) -> int:
    deadline = time.time() + poll_seconds
    match_l = match.lower()
    while time.time() < deadline:
        time.sleep(poll_interval)
        grid = session.get(grid_url, timeout=timeout)
        grid.raise_for_status()
        rows = parse_grid_rows(grid.text)
        hits = [row for row in rows if match_l in row["company_name"].lower()]
        if hits:
            print("GRID MATCH:")
            for row in hits[:3]:
                print(
                    f"  {row['safe_number']} | {row['company_name']} | "
                    f"{row['address']}, {row['city']}, {row['state']} {row['zip']} | "
                    f"{row['import_date']}"
                )
            return 0

        if poll_oracle:
            oracle_hits = [
                row
                for row in oracle_lookup(match)
                if match_l in row.get("COMPANY_NAME", row.get("company_name", "")).lower()
            ]
            if oracle_hits:
                print("ORACLE MATCH:")
                for row in oracle_hits[:3]:
                    safe = row.get("SAFE_NUMBER", row.get("safe_number", ""))
                    name = row.get("COMPANY_NAME", row.get("company_name", ""))
                    print(f"  {safe} | {name}")
                return 0

        print(f"poll... no match for {match!r}")

    print(f"No match for {match!r} within {poll_seconds}s")
    return 1


def submit(args: argparse.Namespace, file_path: Path) -> int:
    try:
        import requests
    except ImportError:
        print("Missing dependency: requests.", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/")
    import_url = urljoin(base_url, IMPORT_PAGE)
    grid_url = urljoin(base_url, GRID_PAGE)

    cookies = cookies_from_chrome(args.cdp_url, base_url, args.timeout)
    if not any(c["name"] == "ASP.NET_SessionId" for c in cookies):
        print("Warning: ASP.NET_SessionId cookie not found.", file=sys.stderr)

    with requests.Session() as session:
        apply_cookies(session, cookies)
        data = form_data_for_import_page(session, base_url, args.timeout, args.email)
        with file_path.open("rb") as handle:
            response = session.post(
                import_url,
                data=data,
                files={
                    "ImportFile": (
                        file_path.name,
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                timeout=args.timeout,
            )
        print(f"POST {import_url}")
        print(f"Status: {response.status_code}")
        print(f"Final URL: {response.url}")
        for line in extract_messages(response.text):
            print(line)
        response.raise_for_status()

        if not args.match:
            return 0
        return poll_for_match(
            session,
            grid_url,
            args.match,
            args.poll_seconds,
            args.poll_interval,
            args.timeout,
            args.poll_oracle,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload Edit Tool company import xlsx via HTTP (DET-style)."
    )
    parser.add_argument("file", help="Company import .xlsx")
    parser.add_argument("--submit", action="store_true", help="Upload and poll")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP)
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument(
        "--match",
        default="",
        help="Company name substring to watch in grid/Oracle (optional)",
    )
    parser.add_argument(
        "--poll-oracle",
        action="store_true",
        help="Also poll Oracle company_search_view during --submit",
    )
    args = parser.parse_args(argv)

    file_path = Path(args.file).expanduser().resolve()
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    endpoint = urljoin(args.base_url.rstrip("/") + "/", IMPORT_PAGE.lstrip("/"))
    print(f"Endpoint: {endpoint}")
    print(f"Grid: {urljoin(args.base_url, GRID_PAGE)}")
    print(f"File: {file_path}")
    print("File field: ImportFile")
    print(f"Email: {args.email}")
    print(f"CDP: {args.cdp_url}")
    print(f"ASP.NET cookie via Chrome CDP: yes")

    if not args.submit:
        print("Dry run only. Add --submit to upload.")
        return 0
    return submit(args, file_path)


if __name__ == "__main__":
    raise SystemExit(main())
