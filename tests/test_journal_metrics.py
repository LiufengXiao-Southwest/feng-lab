"""Tests for journal metric resolution.

The substring-collision cases below are the regression this module exists to
prevent: the old lookup published "International Journal of Sports Medicine"
(real IF 2.3) as IF 9.8 because its name contains "sports medicine".
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from journal_metrics import (  # noqa: E402
    JournalIndex,
    is_domain_relevant,
    display_impact,
    display_tier,
    impact_value,
    normalize_issn,
    normalize_name,
)

PAYLOAD = {
    "updated": "2026-07-27",
    "journals": [
        {
            "name": "Sports Medicine",
            "aliases": ["Sports Med"],
            "issn": ["0112-1642", "1179-2035"],
            "jcr_if": "11.0",
            "jcr_year": "2024",
            "jcr_quartile": "Q1",
            "cas_tier": "医学1区",
            "cas_tier_small": "运动科学1区",
            "cas_top": "医学TOP",
            "cite_doc_2y": 11.01,
        },
        {
            "name": "International Journal of Sports Medicine",
            "aliases": ["Int J Sports Med"],
            "issn": ["0172-4622"],
            "jcr_if": "2.3",
            "jcr_year": "2024",
            "jcr_quartile": "Q2",
            "cas_tier_small": "运动科学4区",
            "cite_doc_2y": 2.4,
        },
        {
            "name": "Orthopaedic Journal of Sports Medicine",
            "issn": ["2325-9671"],
            "jcr_if": "2.9",
            "jcr_year": "2024",
            "cite_doc_2y": 3.1,
        },
        {
            "name": "Molecular & Cellular Biomechanics",
            "issn": ["1556-5297"],
            "cite_doc_2y": 0.4,
        },
        {
            "name": "Journal of Biomechanics",
            "issn": ["0021-9290"],
            "openalex_2yr": 2.31,
            "sjr_quartile": "Q1",
        },
    ],
}


class NormalizationTests(unittest.TestCase):
    def test_abbreviations_fold_to_full_names(self):
        self.assertEqual(
            normalize_name("Br J Sports Med"),
            normalize_name("British Journal of Sports Medicine"),
        )

    def test_leading_article_and_punctuation_ignored(self):
        self.assertEqual(
            normalize_name("The American Journal of Sports Medicine!"),
            normalize_name("American Journal of Sports Medicine"),
        )

    def test_ampersand_and_and_are_equivalent(self):
        self.assertEqual(
            normalize_name("Medicine & Science in Sports"),
            normalize_name("Medicine and Science in Sports"),
        )

    def test_html_entities_are_decoded(self):
        self.assertEqual(
            normalize_name("Molecular &amp; Cellular Biomechanics"),
            normalize_name("Molecular & Cellular Biomechanics"),
        )

    def test_issn_normalization(self):
        self.assertEqual(normalize_issn("01121642"), "0112-1642")
        self.assertEqual(normalize_issn("0112-1642"), "0112-1642")
        self.assertEqual(normalize_issn("not-an-issn"), "")


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.idx = JournalIndex(PAYLOAD)

    def test_longer_name_wins_over_substring(self):
        """The exact bug that published 39 papers with a borrowed IF of 9.8."""
        entry = self.idx.lookup("International Journal of Sports Medicine")
        self.assertEqual(entry["name"], "International Journal of Sports Medicine")
        self.assertEqual(entry["jcr_if"], "2.3")

    def test_orthopaedic_journal_does_not_match_sports_medicine(self):
        entry = self.idx.lookup("Orthopaedic Journal of Sports Medicine")
        self.assertEqual(entry["jcr_if"], "2.9")

    def test_exact_name_still_resolves(self):
        self.assertEqual(self.idx.lookup("Sports Medicine")["jcr_if"], "11.0")

    def test_issn_beats_an_ambiguous_name(self):
        entry = self.idx.lookup("Sports Medicine", ["0172-4622"])
        self.assertEqual(entry["name"], "International Journal of Sports Medicine")

    def test_alias_resolves(self):
        self.assertEqual(self.idx.lookup("Sports Med")["jcr_if"], "11.0")

    def test_html_escaped_venue_resolves(self):
        entry = self.idx.lookup("Molecular &amp; Cellular Biomechanics")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "Molecular & Cellular Biomechanics")

    def test_unknown_venue_returns_none(self):
        self.assertIsNone(self.idx.lookup("Journal of Imaginary Studies"))

    def test_empty_venue_returns_none(self):
        self.assertIsNone(self.idx.lookup(""))

    def test_missing_file_yields_empty_index(self):
        idx = JournalIndex.load(Path("does-not-exist.json"))
        self.assertEqual(len(idx), 0)
        self.assertIsNone(idx.lookup("Sports Medicine"))


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.idx = JournalIndex(PAYLOAD)

    def test_jcr_is_labelled_with_its_year(self):
        value, source = display_impact(self.idx.lookup("Sports Medicine"))
        self.assertEqual(value, "11.0")
        self.assertEqual(source, "JCR 2024")

    def test_falls_back_to_scimago_with_honest_label(self):
        """A SCImago number must never be labelled as an impact factor."""
        value, source = display_impact(self.idx.lookup("Molecular & Cellular Biomechanics"))
        self.assertEqual(value, "0.4")
        self.assertNotIn("JCR", source)
        self.assertIn("SJR", source)

    def test_falls_back_to_openalex_last(self):
        value, source = display_impact(self.idx.lookup("Journal of Biomechanics"))
        self.assertEqual(value, "2.3")
        self.assertIn("OpenAlex", source)

    def test_no_metrics_yields_no_badge(self):
        self.assertEqual(display_impact(None), ("", ""))

    def test_tier_prefers_cas_subcategory(self):
        self.assertEqual(display_tier(self.idx.lookup("Sports Medicine")), "运动科学1区 TOP")

    def test_tier_falls_back_to_quartile(self):
        self.assertEqual(display_tier(self.idx.lookup("Journal of Biomechanics")), "Q1")

    def test_impact_value_prefers_jcr_over_scimago(self):
        self.assertEqual(impact_value(self.idx.lookup("Sports Medicine")), 11.0)

    def test_impact_value_handles_junk(self):
        self.assertEqual(impact_value({"jcr_if": "n/a"}), 0.0)
        self.assertEqual(impact_value(None), 0.0)


class DomainRelevanceTests(unittest.TestCase):
    """A photonics journal cleared the citation-rate fallback into a
    sports-science digest. Citation rate carries no subject information."""

    def test_unrelated_discipline_is_rejected(self):
        self.assertFalse(is_domain_relevant({
            "name": "Photonics",
            "topics": ["Engineering / Electrical and Electronic Engineering",
                       "Physics and Astronomy / Atomic and Molecular Physics, and Optics"],
        }))

    def test_sports_medicine_topic_is_relevant(self):
        self.assertTrue(is_domain_relevant({
            "name": "British Journal of Sports Medicine",
            "topics": ["Medicine / Orthopedics and Sports Medicine"],
        }))

    def test_biomedical_engineering_is_relevant(self):
        self.assertTrue(is_domain_relevant({
            "name": "Annals of Biomedical Engineering",
            "topics": ["Engineering / Biomedical Engineering"],
        }))

    def test_cas_tier_alone_establishes_relevance(self):
        self.assertTrue(is_domain_relevant({"cas_tier_small": "运动科学3区"}))

    def test_scopus_category_alone_establishes_relevance(self):
        self.assertTrue(is_domain_relevant({
            "sjr_categories": {"Orthopedics and Sports Medicine": "Q1"},
        }))

    def test_no_topic_data_is_not_treated_as_irrelevant(self):
        """Absence of evidence is not evidence of absence; the metric gate
        still applies. Scientific Reports resolves with no topics at all."""
        self.assertTrue(is_domain_relevant({"name": "Scientific Reports", "topics": []}))

    def test_none_entry_is_not_relevant(self):
        self.assertFalse(is_domain_relevant(None))


if __name__ == "__main__":
    unittest.main()
