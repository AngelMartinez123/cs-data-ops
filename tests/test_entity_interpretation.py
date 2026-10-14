import unittest

from entity_resolution.interpretation import compare_company
from entity_resolution.models import CompanyEvidence, EntityCandidate


class CompanyInterpretationTests(unittest.TestCase):
    def test_address_conflict_requires_review_even_with_partial_overlap(self):
        evidence = CompanyEvidence(
            company_ref="EXAMPLE_REF",
            company_name="Example LLC",
            address="123 Main Street Suite 4",
        )
        official = EntityCandidate(
            legal_name="Example LLC",
            state_code="PA",
            principal_address="123 Main Street Suite 9",
        )
        comparisons, _, action = compare_company(evidence, official)
        self.assertTrue(
            any(
                item.field == "Principal Address" and item.result == "CONFLICT"
                for item in comparisons
            )
        )
        self.assertEqual(action, "REVIEW SOS / ENTITY MATCH")

    def test_matching_record_produces_structured_comparison(self):
        evidence = CompanyEvidence(
            company_ref="EXAMPLE_REF",
            company_name="Example LLC",
            address="123 Main St",
            city="Harrisburg",
            state="PA",
            zip_code="17101",
            charter_number="1234567",
            sos_status="ACTIVE",
            incorporated_state="PA",
            incorporation_date="2020-01-01",
            domestic_foreign="DOMESTIC",
            location_type="1",
        )
        official = EntityCandidate(
            legal_name="EXAMPLE, L.L.C.",
            state_code="PA",
            entity_number="1234567",
            status="Active",
            formation_date="2020-01-01",
            domestic_foreign="DOMESTIC",
            domestic_jurisdiction="PA",
            principal_address="123 MAIN STREET, HARRISBURG, PA 17101",
        )
        comparisons, findings, action = compare_company(evidence, official)
        self.assertEqual(action, "KEEP CURRENT STRUCTURE")
        self.assertTrue(any(item.field == "Charter Number" for item in comparisons))
        self.assertFalse(any(item.result == "CONFLICT" for item in comparisons))
        self.assertTrue(any("appears consistent" in item for item in findings))

    def test_branch_record_never_auto_owns_entity(self):
        evidence = CompanyEvidence(
            company_ref="EXAMPLE_REF",
            company_name="Example LLC",
            location_type="2",
        )
        official = EntityCandidate(legal_name="EXAMPLE LLC", state_code="PA")
        _, findings, action = compare_company(evidence, official)
        self.assertEqual(action, "REVIEW AS POSSIBLE BRANCH")
        self.assertTrue(any("branch/location" in item for item in findings))

    def test_conflicting_charter_and_jurisdiction_are_visible(self):
        evidence = CompanyEvidence(
            company_ref="EXAMPLE_REF",
            company_name="Example LLC",
            charter_number="111",
            incorporated_state="PA",
        )
        official = EntityCandidate(
            legal_name="EXAMPLE LLC",
            state_code="DE",
            entity_number="222",
            domestic_jurisdiction="DE",
        )
        comparisons, findings, action = compare_company(evidence, official)
        conflicts = {item.field for item in comparisons if item.result == "CONFLICT"}
        self.assertEqual(conflicts, {"Charter Number", "Incorporated State"})
        self.assertEqual(action, "REVIEW SOS / ENTITY MATCH")
        self.assertTrue(any("incorrect" in item for item in findings))

    def test_no_official_match_requires_human_review(self):
        comparisons, findings, action = compare_company(
            CompanyEvidence(company_ref="EXAMPLE_REF"),
            None,
        )
        self.assertEqual(comparisons, [])
        self.assertEqual(action, "HUMAN REVIEW REQUIRED")
        self.assertTrue(findings)


if __name__ == "__main__":
    unittest.main()
