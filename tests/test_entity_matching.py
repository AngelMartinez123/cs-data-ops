import unittest

from entity_resolution.models import Confidence, EntityCandidate, SearchRequest
from entity_resolution.normalize import (
    address_similarity,
    material_name_conflict,
    name_similarity,
    normalize_address,
    normalize_name,
)
from entity_resolution.scoring import score_candidate


class NormalizationTests(unittest.TestCase):
    def test_legal_suffix_and_punctuation_normalize(self):
        self.assertEqual(normalize_name("A.B.C. Holdings, L.L.C."), "A B C HOLDINGS")

    def test_address_abbreviations_normalize(self):
        self.assertEqual(
            normalize_address("123 North Main Street, Suite 4"),
            "123 N MAIN ST STE 4",
        )

    def test_material_numeric_token_is_preserved(self):
        self.assertTrue(
            material_name_conflict("ABC Holdings LLC", "ABC Holdings II LLC")
        )

    def test_name_similarity_ignores_legal_suffix_only(self):
        self.assertEqual(name_similarity("Example LLC", "EXAMPLE, L.L.C."), 1.0)

    def test_address_similarity(self):
        self.assertEqual(
            address_similarity("123 North Main Street", "123 N Main St"),
            1.0,
        )


class ScoringTests(unittest.TestCase):
    def test_name_only_is_not_confirmed(self):
        result = score_candidate(
            SearchRequest(company_name="Example LLC", expected_state="PA"),
            EntityCandidate(legal_name="EXAMPLE, L.L.C.", state_code="PA"),
        )
        self.assertNotEqual(result.score.confidence, Confidence.CONFIRMED)

    def test_name_and_entity_number_confirm(self):
        result = score_candidate(
            SearchRequest(
                company_name="Example LLC",
                expected_state="PA",
                entity_number="1234567",
            ),
            EntityCandidate(
                legal_name="EXAMPLE LLC",
                state_code="PA",
                entity_number="1234567",
            ),
        )
        self.assertEqual(result.score.confidence, Confidence.CONFIRMED)

    def test_conflicting_entity_number_caps_confidence(self):
        result = score_candidate(
            SearchRequest(
                company_name="Example LLC",
                expected_state="PA",
                expected_address="123 Main St",
                entity_number="111",
            ),
            EntityCandidate(
                legal_name="EXAMPLE LLC",
                state_code="PA",
                entity_number="222",
                principal_address="123 Main Street",
            ),
        )
        self.assertIn(
            result.score.confidence,
            {Confidence.POSSIBLE_MATCH, Confidence.NO_MATCH},
        )


if __name__ == "__main__":
    unittest.main()
