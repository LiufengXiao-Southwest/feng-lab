#!/usr/bin/env python3
"""
FENG LAB — Rewrite journal metrics across already-published data.

The old venue lookup matched by loose substring, so 39 of the 190 archived
papers were published with an impact factor of 9.8 that belonged to a different
journal: "Journal of Sports Medicine and Physical Fitness" (real IF 1.3),
"International Journal of Sports Medicine" (2.3), "Orthopaedic Journal of
Sports Medicine" (2.9) and "Sports Medicine - Open" (6.2) all contain the
string "sports medicine".

Correcting the fetcher only fixes papers from today onward. This rewrites the
history: every paper in archive.json, papers.json and the deep-read files is
re-resolved against data/journals.json and gets the correct impact factor,
provenance label and CAS tier.

Run after scripts/update_journal_metrics.py. Idempotent — safe to re-run.

Usage::

    python scripts/backfill_metrics.py --dry-run   # report changes only
    python scripts/backfill_metrics.py             # apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from journal_metrics import JournalIndex, display_impact, display_tier  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

JOURNALS = JournalIndex.load()


def patch(paper: dict) -> tuple[bool, str | None]:
    """Re-resolve one paper's journal metrics. Returns (changed, description)."""
    venue = (paper.get("journal") or "").strip()
    if not venue:
        return False, None

    issns = []
    if paper.get("journal_issn"):
        issns.append(paper["journal_issn"])

    entry = JOURNALS.lookup(venue, issns)
    if not entry:
        return False, None

    new_if, new_src = display_impact(entry)
    tier = display_tier(entry)
    old_if = str(paper.get("impact_factor") or "")

    changed = False
    if old_if != new_if:
        changed = True
    if paper.get("if_source") != new_src or paper.get("journal_tier") != tier:
        changed = True

    if not changed:
        return False, None

    paper["impact_factor"] = new_if
    paper["if_source"] = new_src
    paper["journal_tier"] = tier
    if entry.get("issn"):
        paper["journal_issn"] = entry["issn"][0]
    # Normalize to the canonical name so future lookups hit by exact match.
    paper["journal"] = entry.get("name") or venue

    if old_if and new_if and old_if != new_if:
        return True, f"{venue[:46]:48} IF {old_if:>5} → {new_if:>5}"
    return True, None


def process(path: Path, dry_run: bool) -> tuple[int, list[str]]:
    if not path.exists():
        return 0, []
    payload = json.loads(path.read_text(encoding="utf-8"))
    notes: list[str] = []
    count = 0

    def walk(obj):
        nonlocal count
        if isinstance(obj, dict):
            if "journal" in obj and ("title_en" in obj or "impact_factor" in obj):
                changed, note = patch(obj)
                if changed:
                    count += 1
                    if note:
                        notes.append(note)
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)

    if count and not dry_run:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return count, notes


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill journal metrics into published data")
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    if len(JOURNALS) == 0:
        print("[!] data/journals.json is empty or missing. "
              "Run scripts/update_journal_metrics.py first.")
        return 1

    targets = ["archive.json", "papers.json", "deep_read.json",
               "deep_read_history_full.json"]
    total = 0
    all_notes: list[str] = []

    for name in targets:
        count, notes = process(DATA / name, args.dry_run)
        total += count
        all_notes.extend(notes)
        verb = "would update" if args.dry_run else "updated"
        print(f"  {name:32} {verb} {count} records")

    if all_notes:
        seen = set()
        print(f"\nImpact factors corrected:")
        for note in all_notes:
            if note not in seen:
                seen.add(note)
                print(f"    {note}")

    print(f"\n{'Would update' if args.dry_run else 'Updated'} {total} records total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
