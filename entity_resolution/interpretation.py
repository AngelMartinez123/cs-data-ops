from __future__ import annotations

from .models import CompanyEvidence, EntityCandidate, FieldComparison
from .normalize import address_similarity, normalize_name, normalize_text


def compare_company(
    evidence: CompanyEvidence,
    official: EntityCandidate | None,
) -> tuple[list[FieldComparison], list[str], str]:
    if official is None:
        return (
            [],
            ["No authoritative registration could be confirmed."],
            "HUMAN REVIEW REQUIRED",
        )

    comparisons: list[FieldComparison] = []
    findings: list[str] = []
    conflicts: list[str] = []

    if evidence.company_name or official.legal_name:
        name_match = normalize_name(evidence.company_name) == normalize_name(
            official.legal_name
        ) and bool(evidence.company_name)
        comparisons.append(
            FieldComparison(
                "Legal Name",
                evidence.company_name,
                official.legal_name,
                "MATCH" if name_match else "CONFLICT",
            )
        )
        if name_match:
            findings.append(
                "Company record legal name matches the official legal name."
            )
        else:
            conflicts.append(
                f"Legal name differs: Company record={evidence.company_name!r}; "
                f"official={official.legal_name!r}."
            )

    if evidence.charter_number or official.entity_number:
        left = normalize_text(evidence.charter_number).replace(" ", "")
        right = normalize_text(official.entity_number).replace(" ", "")
        result = (
            "MATCH"
            if left and left == right
            else "NOT_AVAILABLE" if not left or not right else "CONFLICT"
        )
        comparisons.append(
            FieldComparison(
                "Charter Number",
                evidence.charter_number,
                official.entity_number,
                result,
            )
        )
        if result == "MATCH":
            findings.append(
                "Company record charter number matches the official entity number."
            )
        elif result == "CONFLICT":
            conflicts.append("SOS charter/entity number appears incorrect.")

    if evidence.sos_status or official.status:
        status_match = (
            bool(evidence.sos_status)
            and bool(official.status)
            and normalize_text(evidence.sos_status) == normalize_text(official.status)
        )
        comparisons.append(
            FieldComparison(
                "Status",
                evidence.sos_status,
                official.status,
                (
                    "MATCH"
                    if status_match
                    else (
                        "NOT_AVAILABLE"
                        if not evidence.sos_status or not official.status
                        else "CONFLICT"
                    )
                ),
            )
        )
        if status_match:
            findings.append("Company record SOS status matches the official status.")
        elif evidence.sos_status and official.status:
            conflicts.append(
                f"SOS status may be stale: Company record={evidence.sos_status!r}; "
                f"official={official.status!r}."
            )

    official_jurisdiction = official.domestic_jurisdiction or official.state_code
    if evidence.incorporated_state or official_jurisdiction:
        jurisdiction_match = (
            bool(evidence.incorporated_state)
            and bool(official_jurisdiction)
            and evidence.incorporated_state.upper() == official_jurisdiction.upper()
        )
        comparisons.append(
            FieldComparison(
                "Incorporated State",
                evidence.incorporated_state,
                official_jurisdiction,
                (
                    "MATCH"
                    if jurisdiction_match
                    else (
                        "NOT_AVAILABLE"
                        if not evidence.incorporated_state or not official_jurisdiction
                        else "CONFLICT"
                    )
                ),
            )
        )
        if jurisdiction_match:
            findings.append(
                "Company record incorporated state matches official jurisdiction."
            )
        elif evidence.incorporated_state and official_jurisdiction:
            conflicts.append(
                f"Incorporated state conflict: Company record={evidence.incorporated_state}; "
                f"official={official_jurisdiction}."
            )

    if evidence.incorporation_date or official.formation_date:
        date_match = (
            bool(evidence.incorporation_date)
            and bool(official.formation_date)
            and evidence.incorporation_date[:10] == official.formation_date[:10]
        )
        comparisons.append(
            FieldComparison(
                "Incorporation Date",
                evidence.incorporation_date,
                official.formation_date,
                (
                    "MATCH"
                    if date_match
                    else (
                        "NOT_AVAILABLE"
                        if not evidence.incorporation_date
                        or not official.formation_date
                        else "CONFLICT"
                    )
                ),
            )
        )
        if not date_match and evidence.incorporation_date and official.formation_date:
            conflicts.append("Company record and official incorporation dates differ.")

    company_address = " ".join(
        value
        for value in [
            evidence.address,
            evidence.city,
            evidence.state,
            evidence.zip_code,
        ]
        if value
    )
    if company_address or official.principal_address:
        similarity = address_similarity(company_address, official.principal_address)
        address_result = (
            "MATCH"
            if similarity == 1
            else (
                "CLOSE_MATCH"
                if similarity >= 0.75
                else (
                    "NOT_AVAILABLE"
                    if not company_address or not official.principal_address
                    else "CONFLICT"
                )
            )
        )
        comparisons.append(
            FieldComparison(
                "Principal Address",
                company_address,
                official.principal_address,
                address_result,
            )
        )
        if similarity >= 0.75:
            findings.append(
                "Company record and official principal addresses are close matches."
            )
        elif address_result == "CONFLICT":
            conflicts.append(
                "Company record and official principal addresses materially differ."
            )

    if evidence.domestic_foreign or official.domestic_foreign:
        classification_match = (
            bool(evidence.domestic_foreign)
            and bool(official.domestic_foreign)
            and normalize_text(evidence.domestic_foreign)
            == normalize_text(official.domestic_foreign)
        )
        comparisons.append(
            FieldComparison(
                "Domestic/Foreign",
                evidence.domestic_foreign,
                official.domestic_foreign,
                (
                    "MATCH"
                    if classification_match
                    else (
                        "NOT_AVAILABLE"
                        if not evidence.domestic_foreign
                        or not official.domestic_foreign
                        else "CONFLICT"
                    )
                ),
            )
        )
        if (
            evidence.domestic_foreign
            and official.domestic_foreign
            and not classification_match
        ):
            conflicts.append("Company record domestic/foreign classification differs.")

    if official.domestic_foreign.upper().startswith("FOREIGN"):
        findings.append(
            "Foreign registration found; domestic jurisdiction should also be checked."
        )

    if evidence.location_type == "2":
        conflicts.append(
            "Current company record is a branch/location; SOS evidence alone does not prove that it "
            "should own the legal entity."
        )
        action = "REVIEW AS POSSIBLE BRANCH"
    elif conflicts:
        action = "REVIEW SOS / ENTITY MATCH"
    else:
        action = "KEEP CURRENT STRUCTURE"
        findings.append(
            "Existing company record appears consistent with the official entity evidence."
        )

    return comparisons, findings + conflicts, action
