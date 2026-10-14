from __future__ import annotations

import re
from difflib import SequenceMatcher


LEGAL_SUFFIXES = {
    "CO",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "INC",
    "INCORPORATED",
    "LC",
    "LLC",
    "LIMITED",
    "LP",
    "LLP",
    "LTD",
    "PLLC",
    "PC",
    "PROFESSIONAL",
    "ASSOCIATION",
}

STREET_EQUIVALENTS = {
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "BUILDING": "BLDG",
    "COURT": "CT",
    "DRIVE": "DR",
    "EAST": "E",
    "FLOOR": "FL",
    "HIGHWAY": "HWY",
    "LANE": "LN",
    "NORTH": "N",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "PARKWAY": "PKWY",
    "PLACE": "PL",
    "ROAD": "RD",
    "SOUTH": "S",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
    "STREET": "ST",
    "SUITE": "STE",
    "TERRACE": "TER",
    "WEST": "W",
}


def normalize_text(value: str) -> str:
    text = (value or "").upper().replace("&", " AND ")
    text = re.sub(r"\bL[\s.]*L[\s.]*C\b", " LLC ", text)
    text = re.sub(r"\bL[\s.]*L[\s.]*P\b", " LLP ", text)
    text = re.sub(r"\bI[\s.]*N[\s.]*C\b", " INC ", text)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_name(value: str, *, strip_legal_suffix: bool = True) -> str:
    tokens = normalize_text(value).split()
    if strip_legal_suffix:
        while tokens and tokens[-1] in LEGAL_SUFFIXES:
            tokens.pop()
    return " ".join(tokens)


def normalize_address(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"\bP O BOX\b", "PO BOX", text)
    tokens = [STREET_EQUIVALENTS.get(token, token) for token in text.split()]
    return " ".join(tokens)


def normalize_zip(value: str) -> str:
    return re.sub(r"\D", "", value or "")[:5]


def token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def name_similarity(left: str, right: str) -> float:
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    token_score = token_similarity(a, b)
    sequence_score = SequenceMatcher(None, a, b).ratio()
    return round(max(token_score, (token_score + sequence_score) / 2), 3)


def address_similarity(left: str, right: str) -> float:
    a = normalize_address(left)
    b = normalize_address(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return round(token_similarity(a, b), 3)


def material_name_conflict(left: str, right: str) -> bool:
    """Detect material qualifiers that name similarity can otherwise hide."""
    a = normalize_name(left).split()
    b = normalize_name(right).split()
    if not a or not b:
        return False
    ordinal_tokens = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"}
    numeric_a = {token for token in a if token.isdigit() or token in ordinal_tokens}
    numeric_b = {token for token in b if token.isdigit() or token in ordinal_tokens}
    if numeric_a != numeric_b and (numeric_a or numeric_b):
        return True
    qualifiers = {
        "HOLDINGS",
        "MANAGEMENT",
        "PROPERTIES",
        "SERVICES",
        "TEXAS",
        "CALIFORNIA",
        "FLORIDA",
        "NEW",
        "YORK",
    }
    return ({*a} & qualifiers) != ({*b} & qualifiers)


def name_variants(name: str) -> list[str]:
    original = normalize_text(name)
    stripped = normalize_name(name)
    variants = [original, stripped]
    if " AND " in original:
        variants.append(original.replace(" AND ", " & "))
    words = stripped.split()
    if len(words) > 2:
        variants.append(" ".join(words[:3]))
    return list(dict.fromkeys(value for value in variants if value))
