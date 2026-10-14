from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class AccessMethod(str, Enum):
    API = "API"
    DIRECT_HTTP = "DIRECT_HTTP"
    BROWSER_AUTOMATION = "BROWSER_AUTOMATION"
    MANUAL_ONLY = "MANUAL_ONLY"


class AdapterStatus(str, Enum):
    WORKING = "WORKING"
    DEGRADED = "DEGRADED"
    MANUAL_ONLY = "MANUAL_ONLY"
    BROKEN = "BROKEN"
    UNVERIFIED = "UNVERIFIED"


class SearchOutcome(str, Enum):
    ENTITY_FOUND = "ENTITY_FOUND"
    NO_ENTITY_FOUND = "NO_ENTITY_FOUND"
    SEARCH_UNAVAILABLE = "SEARCH_UNAVAILABLE"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    ADAPTER_ERROR = "ADAPTER_ERROR"


class Confidence(str, Enum):
    CONFIRMED = "CONFIRMED"
    VERY_STRONG_MATCH = "VERY_STRONG_MATCH"
    PROBABLE_MATCH = "PROBABLE_MATCH"
    POSSIBLE_MATCH = "POSSIBLE_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(slots=True)
class StateConfig:
    state: str
    state_code: str
    agency_name: str
    official_agency_homepage: str
    business_search_url: str
    search_system_name: str
    search_method: AccessMethod
    adapter_status: AdapterStatus
    searchable_by_name: bool
    searchable_by_entity_number: bool
    searchable_by_agent: bool
    searchable_by_officer: bool
    searchable_by_address: bool
    supports_partial_name_search: bool
    supports_exact_name_search: bool
    supports_status_filter: bool
    requires_login: bool
    requires_captcha: bool
    requires_javascript: bool
    requires_terms_acceptance: bool
    free_search: bool
    paid_details: bool
    bulk_data_available: bool
    api_available: bool
    robots_or_automation_notes: str
    rate_limit_notes: str
    result_fields: list[str] = field(default_factory=list)
    entity_detail_fields: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    evidence_urls: list[str] = field(default_factory=list)
    last_verified: str = ""
    notes: str = ""
    adapter: str = "manual"
    adapter_options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StateConfig":
        data = dict(raw)
        data["state_code"] = str(data["state_code"]).upper()
        data["search_method"] = AccessMethod(data["search_method"])
        data["adapter_status"] = AdapterStatus(data["adapter_status"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(slots=True)
class SourceEvidence:
    state_code: str
    agency_name: str
    source_url: str
    retrieved_at: str
    search_query: str
    detail_url: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EntityCandidate:
    legal_name: str
    state_code: str
    entity_number: str = ""
    entity_type: str = ""
    status: str = ""
    formation_date: str = ""
    domestic_foreign: str = ""
    domestic_jurisdiction: str = ""
    principal_address: str = ""
    mailing_address: str = ""
    registered_agent: str = ""
    officers: list[str] = field(default_factory=list)
    alternate_names: list[str] = field(default_factory=list)
    detail_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    evidence: SourceEvidence | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(slots=True)
class SearchRequest:
    company_name: str
    expected_state: str = ""
    expected_address: str = ""
    company_ref: str = ""
    entity_number: str = ""
    incorporated_state: str = ""
    alternate_names: list[str] = field(default_factory=list)
    registered_agent: str = ""
    officers: list[str] = field(default_factory=list)
    formation_date: str = ""
    max_states: int = 4


@dataclass(slots=True)
class ScoreExplanation:
    score: int
    confidence: Confidence
    positive_factors: list[str] = field(default_factory=list)
    conflicting_factors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateAssessment:
    candidate: EntityCandidate
    score: ScoreExplanation


@dataclass(slots=True)
class CompanyEvidence:
    company_ref: str
    company_name: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    charter_number: str = ""
    sos_status: str = ""
    incorporated_state: str = ""
    incorporation_date: str = ""
    domestic_foreign: str = ""
    location_type: str = ""
    hq_company_ref: str = ""
    parent_company_ref: str = ""
    branch_count: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CompanyEvidence":
        allowed = set(cls.__dataclass_fields__)
        values = {key: value for key, value in raw.items() if key in allowed}
        values.setdefault("company_ref", str(raw.get("COMPANY_REF", "")))
        return cls(**values)


@dataclass(slots=True)
class FieldComparison:
    field: str
    company_value: str
    official_value: str
    result: str


@dataclass(slots=True)
class SearchAttempt:
    state_code: str
    agency_name: str
    source_url: str
    query: str
    outcome: SearchOutcome
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SearchResult:
    request: SearchRequest
    outcome: SearchOutcome
    searched_states: list[str] = field(default_factory=list)
    search_attempts: list[SearchAttempt] = field(default_factory=list)
    assessments: list[CandidateAssessment] = field(default_factory=list)
    best_match: CandidateAssessment | None = None
    conflicting_evidence: list[str] = field(default_factory=list)
    company_comparison: list[FieldComparison] = field(default_factory=list)
    company_interpretation: list[str] = field(default_factory=list)
    recommended_action: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))
