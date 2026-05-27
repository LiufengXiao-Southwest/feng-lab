import datetime
import json
import tempfile
import types
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.modules.setdefault("requests", types.SimpleNamespace(get=None))

import fetch_papers


class FetchPapersTests(unittest.TestCase):
    def test_select_top_papers_sorts_by_citations_if_and_year(self):
        papers = [
            {"id": "old", "title_en": "old", "citation_count": 5, "impact_factor": "4.0", "year": 2026},
            {"id": "low-if", "title_en": "low-if", "citation_count": 10, "impact_factor": "2.0", "year": 2026},
            {"id": "high-if", "title_en": "high-if", "citation_count": 10, "impact_factor": "8.0", "year": 2024},
            {"id": "newer", "title_en": "newer", "citation_count": 10, "impact_factor": "8.0", "year": 2026},
            {"id": "fifth", "title_en": "fifth", "citation_count": 4, "impact_factor": "", "year": 2026},
            {"id": "sixth", "title_en": "sixth", "citation_count": 3, "impact_factor": "9.0", "year": 2026},
            {"id": "seventh", "title_en": "seventh", "citation_count": 2, "impact_factor": "9.0", "year": 2026},
        ]

        selected = fetch_papers.select_top_daily_papers(papers)

        self.assertEqual(
            [p["id"] for p in selected],
            ["newer", "high-if", "low-if", "old", "fifth", "sixth"],
        )

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


if __name__ == "__main__":
    unittest.main()
