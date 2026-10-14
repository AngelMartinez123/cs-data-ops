from __future__ import annotations

from .models import (
    CandidateAssessment,
    Confidence,
    EntityCandidate,
    ScoreExplanation,
    SearchRequest,
)
from .normalize import (
    address_similarity,
    material_name_conflict,
    name_similarity,
    normalize_name,
    normalize_text,
)


def score_candidate(
    request: SearchRequest, candidate: EntityCandidate
) -> CandidateAssessment:
    points = 0
    positives: list[str] = []
    conflicts: list[str] = []

    requested_name = normalize_name(request.company_name)
    candidate_name = normalize_name(candidate.legal_name)
    similarity = name_similarity(request.company_name, candidate.legal_name)
    exact_name = bool(requested_name and requested_name == candidate_name)
    material_conflict = material_name_conflict(
        request.company_name, candidate.legal_name
    )

    if exact_name:
        points += 40
        positives.append("exact normalized legal name (+40)")
    elif similarity >= 0.9 and not material_conflict:
        points += 32
        positives.append(f"near-exact legal name {similarity:.0%} (+32)")
    elif similarity >= 0.72:
        points += 20
        positives.append(f"similar legal name {similarity:.0%} (+20)")
    else:
        conflicts.append(f"weak legal-name similarity {similarity:.0%}")

    if material_conflict:
        points -= 20
        conflicts.append("material name qualifier or numeric-token conflict (-20)")

    entity_match = False
    if request.entity_number and candidate.entity_number:
        left = normalize_text(request.entity_number).replace(" ", "")
        right = normalize_text(candidate.entity_number).replace(" ", "")
        if left == right:
            entity_match = True
            points += 30
            positives.append("matching entity/charter number (+30)")
        else:
            points -= 30
            conflicts.append("conflicting entity/charter number (-30)")

    address_score = address_similarity(
        request.expected_address, candidate.principal_address
    )
    if address_score == 1:
        points += 25
        positives.append("exact normalized principal address (+25)")
    elif address_score >= 0.75:
        points += 20
        positives.append(f"near-exact principal address {address_score:.0%} (+20)")
    elif (
        request.expected_address
        and candidate.principal_address
        and address_score < 0.35
    ):
        points -= 25
        conflicts.append("materially different principal address (-25)")

    expected_jurisdiction = (
        (request.incorporated_state or request.expected_state).strip().upper()
    )
    candidate_jurisdiction = (
        (candidate.domestic_jurisdiction or candidate.state_code).strip().upper()
    )
    if expected_jurisdiction:
        if expected_jurisdiction == candidate_jurisdiction:
            points += 10
            positives.append("expected incorporation jurisdiction (+10)")
        elif (
            candidate.domestic_foreign.upper().startswith("FOREIGN")
            and request.expected_state.upper() == candidate.state_code.upper()
        ):
            positives.append("foreign qualification found in expected state")
        else:
            points -= 15
            conflicts.append("conflicting incorporation jurisdiction (-15)")

    if request.registered_agent and candidate.registered_agent:
        if name_similarity(request.registered_agent, candidate.registered_agent) >= 0.9:
            points += 15
            positives.append("registered-agent match (+15)")

    requested_officers = {normalize_name(value) for value in request.officers}
    candidate_officers = {normalize_name(value) for value in candidate.officers}
    officer_matches = (requested_officers & candidate_officers) - {""}
    if officer_matches:
        points += 15
        positives.append("officer/member match (+15)")

    if request.formation_date and candidate.formation_date:
        if request.formation_date == candidate.formation_date:
            points += 10
            positives.append("matching formation date (+10)")
        else:
            conflicts.append("formation dates differ")

    points = max(-100, min(points, 100))
    confidence = _confidence(
        points=points,
        exact_name=exact_name,
        entity_match=entity_match,
        address_score=address_score,
        material_conflict=material_conflict,
        conflicts=conflicts,
    )
    return CandidateAssessment(
        candidate=candidate,
        score=ScoreExplanation(
            score=points,
            confidence=confidence,
            positive_factors=positives,
            conflicting_factors=conflicts,
        ),
    )


def _confidence(
    *,
    points: int,
    exact_name: bool,
    entity_match: bool,
    address_score: float,
    material_conflict: bool,
    conflicts: list[str],
) -> Confidence:
    if material_conflict or any("conflicting entity" in item for item in conflicts):
        return Confidence.POSSIBLE_MATCH if points >= 35 else Confidence.NO_MATCH
    if entity_match and exact_name:
        return Confidence.CONFIRMED
    if exact_name and address_score >= 0.75 and points >= 65:
        return Confidence.CONFIRMED
    if points >= 70:
        return Confidence.VERY_STRONG_MATCH
    if points >= 55:
        return Confidence.PROBABLE_MATCH
    if points >= 30:
        return Confidence.POSSIBLE_MATCH
    return Confidence.NO_MATCH
