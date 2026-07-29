#!/usr/bin/env python3
"""
FENG LAB — Drop archived papers that today's pipeline would not have accepted.

One-off cleanup. The old fetcher had two holes: any journal present in its
40-entry dict passed unconditionally, and the "preprint" category skipped the
quality gate entirely, which let ordinary conference papers in through that
door. 70 of 199 archived papers arrived that way.

Applies the *current* acceptance logic, faithfully — including the split
between journals and preprints, so genuine bioRxiv/medRxiv entries are kept
rather than judged against a journal impact floor they could never meet.

Usage::

    python scripts/prune_archive.py --dry-run
    python scripts/prune_archive.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import fetch_papers as F  # noqa: E402
from journal_metrics import is_domain_relevant  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


# Used only to re-file papers the old preprint bypass mis-categorised. Keyword
# order matters: the first list to match wins.
_RECATEGORISE = [
    ("supplements", ("supplement", "creatine", "caffeine", "nitrate", "protein intake",
                     "collagen", "beta-alanine", "nutrition", "ergogenic", "补剂", "营养")),
    ("biomechanics", ("biomechanic", "kinematic", "kinetic", "gait", "emg",
                      "electromyograph", "plantar", "motion capture", "imu",
                      "joint moment", "力学", "步态", "肌电")),
    ("performance", ("performance", "training", "strength", "sprint", "endurance",
                     "vo2", "power output", "fatigue", "表现", "训练")),
]


def recategorise(paper: dict) -> str:
    blob = " ".join(str(paper.get(f) or "") for f in
                    ("title_en", "title_zh", "abstract_en", "abstract_zh")).lower()
    for category, keywords in _RECATEGORISE:
        if any(k in blob for k in keywords):
            return category
    return "performance"   # broadest of the three


def keeps(paper: dict) -> tuple[bool, str]:
    """Would today's pipeline accept this paper? Returns (keep, reason).

    A paper filed under "preprint" that is not one is judged as the journal
    paper it actually is, not deleted outright. The old bypass mislabelled
    genuinely good work — SJMSS, JSCR and Frontiers in Sports and Active Living
    papers all sit in that category — and a filing mistake is not a quality
    problem. Those are kept and re-filed; only the ones that also fail the
    journal gate are dropped.
    """
    venue = (paper.get("journal") or "").strip()
    doi = (paper.get("doi") or "").strip()
    entry = F.JOURNALS.lookup(venue, [paper.get("journal_issn") or ""])

    if paper.get("category") == "preprint":
        shaped = {"externalIds": {"DOI": doi}}
        if F._looks_like_preprint(shaped, entry, venue):
            return True, "预印本"
        if entry and F._passes_gate(entry):
            paper["category"] = recategorise(paper)
            return True, f"错分预印本，已改判为 {paper['category']}"
        return False, "预印本类目下的非预印本，且期刊不达标"

    if not entry:
        return False, "期刊未收录"
    if F._passes_gate(entry):
        return True, "通过"
    if not is_domain_relevant(entry):
        return False, "学科不相关"
    return False, "指标不达标"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if len(F.JOURNALS) == 0:
        print("[!] data/journals.json is empty. Run update_journal_metrics.py first.")
        return 1

    removed = Counter()
    kept_reasons = Counter()
    removed_by_journal = Counter()
    kept_total = dropped_total = 0

    archive = json.loads((DATA / "archive.json").read_text(encoding="utf-8"))
    new_dates: dict[str, list] = {}
    for date, papers in archive.get("dates", {}).items():
        keep_list = []
        for p in papers:
            ok, reason = keeps(p)
            if ok:
                keep_list.append(p)
                kept_total += 1
                kept_reasons[reason] += 1
            else:
                dropped_total += 1
                removed[reason] += 1
                removed_by_journal[(p.get("journal") or "?")[:52]] += 1
        if keep_list:
            new_dates[date] = keep_list

    emptied = len(archive.get("dates", {})) - len(new_dates)

    print(f"归档: 保留 {kept_total} 篇，删除 {dropped_total} 篇")
    print(f"      {len(new_dates)} 天保留，{emptied} 天变空被移除")
    print("\n删除原因:")
    for reason, n in removed.most_common():
        print(f"  {n:4}  {reason}")
    print("\n按期刊:")
    for journal, n in removed_by_journal.most_common(15):
        print(f"  {n:4}  {journal}")

    # papers.json holds the current homepage; apply the same rule.
    today = json.loads((DATA / "papers.json").read_text(encoding="utf-8"))
    today_keep = [p for p in today.get("papers", []) if keeps(p)[0]]
    print(f"\n首页: {len(today.get('papers', []))} 篇 → {len(today_keep)} 篇")

    if args.dry_run:
        print("\n--dry-run: 未写入。")
        return 0

    archive["dates"] = new_dates
    if new_dates:
        archive["last_updated"] = max(new_dates)
    (DATA / "archive.json").write_text(
        json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

    today["papers"] = today_keep
    (DATA / "papers.json").write_text(
        json.dumps(today, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n✓ 已写入 archive.json 与 papers.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
