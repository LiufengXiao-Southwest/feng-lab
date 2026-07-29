import datetime
import json
import tempfile
import types
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.modules.setdefault("requests", types.SimpleNamespace(get=None, RequestException=Exception))

import fetch_papers


TODAY = datetime.date(2026, 7, 27)


def paper(pid, *, citations=0, impact="", year=2026, evidence=""):
    return {
        "id": pid,
        "title_en": pid,
        "citation_count": citations,
        "impact_factor": impact,
        "year": year,
        "evidence": evidence,
    }


class RankingTests(unittest.TestCase):
    """The digest ranks by citation *rate*, not raw citation count.

    Sorting by total citations structurally favoured the oldest paper in the
    3-year window, so a 'daily' digest kept resurfacing old work.
    """

    def test_recent_paper_beats_older_paper_with_more_total_citations(self):
        fresh = paper("fresh", citations=6, impact="5.0", year=2026)
        stale = paper("stale", citations=30, impact="5.0", year=2023)
        self.assertGreater(
            fetch_papers.paper_score(fresh, TODAY),
            fetch_papers.paper_score(stale, TODAY),
        )

    def test_impact_factor_breaks_ties_between_equals(self):
        high = paper("high", citations=10, impact="9.0", year=2025)
        low = paper("low", citations=10, impact="2.0", year=2025)
        self.assertGreater(
            fetch_papers.paper_score(high, TODAY),
            fetch_papers.paper_score(low, TODAY),
        )

    def test_meta_analysis_outranks_equivalent_primary_study(self):
        meta = paper("meta", citations=5, impact="4.0", year=2026, evidence="meta")
        plain = paper("plain", citations=5, impact="4.0", year=2026)
        self.assertGreater(
            fetch_papers.paper_score(meta, TODAY),
            fetch_papers.paper_score(plain, TODAY),
        )

    def test_uncited_new_paper_still_scores_above_zero(self):
        self.assertGreater(
            fetch_papers.paper_score(paper("new", citations=0, impact="", year=2026), TODAY),
            0,
        )

    def test_malformed_impact_factor_does_not_raise(self):
        self.assertIsInstance(
            fetch_papers.paper_score(paper("junk", impact="n/a"), TODAY), float
        )

    def test_select_top_daily_papers_dedupes_and_caps(self):
        papers = [paper(f"p{i}", citations=i, year=2026) for i in range(10)]
        papers.append(dict(papers[0]))  # duplicate title
        selected = fetch_papers.select_top_daily_papers(papers, limit=6)
        self.assertEqual(len(selected), 6)
        self.assertEqual(len({p["id"] for p in selected}), 6)


class PreprintDetectionTests(unittest.TestCase):
    """The preprint category used to be a bypass for the quality gate."""

    def test_biorxiv_doi_is_a_preprint(self):
        self.assertTrue(fetch_papers._looks_like_preprint(
            {"externalIds": {"DOI": "10.1101/2024.01.01.573000"}}, None, ""))

    def test_arxiv_id_is_a_preprint(self):
        self.assertTrue(fetch_papers._looks_like_preprint(
            {"externalIds": {"ArXiv": "2401.00001"}}, None, ""))

    def test_flagged_preprint_server_is_a_preprint(self):
        self.assertTrue(fetch_papers._looks_like_preprint(
            {}, {"is_preprint_server": True}, "bioRxiv"))

    def test_ordinary_journal_is_not_a_preprint(self):
        self.assertFalse(fetch_papers._looks_like_preprint(
            {"externalIds": {"DOI": "10.1136/bjsports-2020-102955"}},
            {"is_preprint_server": False},
            "British Journal of Sports Medicine"))


class EvidenceLevelTests(unittest.TestCase):
    def test_meta_analysis_wins_over_review_when_both_present(self):
        self.assertEqual(
            fetch_papers._evidence_level({"publicationTypes": ["Review", "MetaAnalysis"]}),
            "meta")

    def test_clinical_trial_detected(self):
        self.assertEqual(
            fetch_papers._evidence_level({"publicationTypes": ["ClinicalTrial"]}), "trial")

    def test_missing_publication_types_is_blank(self):
        self.assertEqual(fetch_papers._evidence_level({}), "")


class WriteOutputTests(unittest.TestCase):
    def test_write_daily_outputs_overwrites_today_and_appends_archive_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            today_file = Path(tmp) / "papers.json"
            archive_file = Path(tmp) / "archive.json"
            today = datetime.date(2026, 5, 27)
            archive_file.write_text(
                json.dumps(
                    {
                        "last_updated": "2026-05-26",
                        "dates": {
                            "2026-05-26": [{"id": "kept", "date_added": "2026-05-26"}]
                        },
                    }
                ),
                encoding="utf-8",
            )

            fetch_papers.write_daily_outputs(
                [{"id": "today", "date_added": "2026-04-01"}],
                today_file,
                archive_file,
                today,
            )

            today_json = json.loads(today_file.read_text(encoding="utf-8"))
            archive_json = json.loads(archive_file.read_text(encoding="utf-8"))

            self.assertEqual(today_json["last_updated"], "2026-05-27")
            self.assertEqual(today_json["papers"], [{"id": "today", "date_added": "2026-05-27"}])
            self.assertEqual(sorted(archive_json["dates"].keys()), ["2026-05-26", "2026-05-27"])
            self.assertEqual(archive_json["dates"]["2026-05-26"][0]["id"], "kept")
            self.assertEqual(archive_json["dates"]["2026-05-27"][0]["id"], "today")



class RepeatSuppressionTests(unittest.TestCase):
    """The digest used to repeat itself: 190 archived entries, 66 distinct papers."""

    def _archive(self, tmp, dates):
        path = Path(tmp) / "archive.json"
        path.write_text(json.dumps({"dates": dates}), encoding="utf-8")
        return path

    def test_recent_papers_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._archive(tmp, {
                "2026-07-20": [{"id": "seen", "doi": "10.1/seen"}],
            })
            seen = fetch_papers.recently_published(path, days=30, today=TODAY)
            self.assertIn("10.1/seen", seen)
            self.assertIn("seen", seen)

    def test_papers_outside_the_window_are_eligible_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._archive(tmp, {
                "2026-01-01": [{"id": "old", "doi": "10.1/old"}],
            })
            self.assertEqual(fetch_papers.recently_published(path, days=30, today=TODAY), set())

    def test_missing_archive_excludes_nothing(self):
        self.assertEqual(
            fetch_papers.recently_published(Path("no-such-file.json"), today=TODAY), set())

    def test_selection_prefers_fresh_over_higher_scoring_repeat(self):
        stale = paper("stale", citations=99, impact="20.0", year=2026)
        stale["doi"] = "10.1/stale"
        fresh = paper("fresh", citations=1, impact="3.0", year=2026)
        fresh["doi"] = "10.1/fresh"
        selected = fetch_papers.select_top_daily_papers(
            [stale, fresh], limit=1, exclude={"10.1/stale"})
        self.assertEqual([p["id"] for p in selected], ["fresh"])

    def test_repeats_backfill_rather_than_shipping_an_empty_digest(self):
        stale = paper("stale", citations=10, impact="5.0", year=2026)
        stale["doi"] = "10.1/stale"
        selected = fetch_papers.select_top_daily_papers(
            [stale], limit=6, exclude={"10.1/stale"})
        self.assertEqual([p["id"] for p in selected], ["stale"])

if __name__ == "__main__":
    unittest.main()
