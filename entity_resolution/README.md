# Explainable entity resolution

An offline extract of registry research tooling developed in September 2026.
It compares supplied candidate records and explains the evidence behind a match.
It does not connect to registries or databases.

The scoring combines normalized legal names, registration identifiers,
addresses, jurisdiction, officers, agents, and formation dates. Numeric name
tokens and material qualifiers remain significant. A name alone cannot reach
`CONFIRMED`; conflicting registration identifiers cap confidence.

```python
from entity_resolution.models import EntityCandidate, SearchRequest
from entity_resolution.scoring import score_candidate

request = SearchRequest(
    company_name="Example Holdings LLC",
    expected_state="PA",
    entity_number="EXAMPLE-001",
)
candidate = EntityCandidate(
    legal_name="EXAMPLE HOLDINGS, L.L.C.",
    state_code="PA",
    entity_number="EXAMPLE-001",
)
assessment = score_candidate(request, candidate)
print(assessment.score.confidence.value)
print(assessment.score.positive_factors)
```

`interpretation.compare_company` compares a supplied company record with a
registration candidate and returns field comparisons, findings, and a review
recommendation. A branch record always receives branch review.

Scores are heuristics, not calibrated probabilities or proof of legal identity.
`CONFIRMED` describes the scoring rule, not permission to update a record. Legal
form normalization can hide meaningful differences, and the qualifier list is
not exhaustive. Review conflicts and original evidence before taking action.

This release includes the offline matching and comparison layer only. Live
adapters, employer-specific enrichment, registry exports, and actual research
results are excluded. The data contracts retain fields for a broader research
workflow; no live search service is included.

Run the synthetic tests from the repository root:

```powershell
python -m unittest discover -s tests -p "test_entity_*.py" -v
```
