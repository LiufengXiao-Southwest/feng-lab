#!/usr/bin/env python3
"""
FENG LAB — Daily Literature Fetcher
Searches Semantic Scholar for papers on configured topics.
Merges new findings into data/papers.json.
"""

import json
import time
import hashlib
import datetime
import requests
from pathlib import Path

TODAY = datetime.date.today().isoformat()
DATA_FILE = Path(__file__).parent.parent / "data" / "papers.json"
MAX_PAPERS   = 80
DAILY_LIMIT  = 2   # New papers fetched per category per day (total = 6)

# ── Search topics (first query in each list is highest priority) ─────────────
SEARCHES = {
    "biomechanics": [
        "movement phenotype gait biomechanics IMU EMG plantar pressure",
        "multi-sensor fusion human motion analysis sports",
        "muscle synergy electromyography running locomotion",
    ],
    "performance": [
        "rate of force development neuromuscular athletic performance",
        "sprint jump training load sports performance",
        "running economy fatigue biomechanics",
    ],
    "supplements": [
        "creatine collagen caffeine sports supplement exercise RCT",
        "ergogenic aids sports nutrition randomized controlled trial",
        "nitrate beta-alanine sport performance supplementation",
    ],
}

SS_URL    = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = "title,authors,year,abstract,externalIds,publicationDate,venue,isOpenAccess,openAccessPdf"

# ── Fetch ────────────────────────────────────────────────────────────────────
def fetch_ss(query: str, category: str, limit: int = 4) -> list:
    papers = []
    try:
        params = {
            "query": query,
            "fields": SS_FIELDS,
            "limit": limit,
            "publicationDateOrYear": f"{datetime.date.today().year - 1}:",
        }
        r = requests.get(SS_URL, params=params, timeout=20)
        r.raise_for_status()

        for p in r.json().get("data", []):
            title = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not title or not abstract or len(abstract) < 80:
                continue

            doi = p.get("externalIds", {}).get("DOI", "")
            authors = [a.get("name", "") for a in (p.get("authors") or [])[:5]]
            is_oa = bool(p.get("isOpenAccess"))
            oa_pdf = p.get("openAccessPdf") or {}
            pdf_url = oa_pdf.get("url", "")

            papers.append({
                "id": hashlib.md5((title + str(p.get("year", ""))).encode()).hexdigest()[:8],
                "title_en":       title,
                "title_zh":       "",
                "authors":        authors,
                "journal":        (p.get("venue") or ""),
                "year":           (p.get("year") or datetime.date.today().year),
                "date_added":     TODAY,
                "category":       category,
                "doi":            doi,
                "is_open_access": is_oa,
                "pdf_url":        pdf_url,
                "abstract_en":    abstract[:900],
                "abstract_zh":    "",
                "keywords":       [],
            })

        time.sleep(1.2)  # Be polite to the API
    except Exception as e:
        print(f"  [!] Error for '{query[:40]}': {e}")
    return papers


# ── Deduplication ────────────────────────────────────────────────────────────
def dedupe(papers: list) -> list:
    seen, result = set(), []
    for p in papers:
        key = (p.get("doi") or "").strip() or p.get("title_en", "").lower()[:60]
        if key and key not in seen:
            seen.add(key)
            result.append(p)
    return result


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print(f"FENG LAB — Daily fetch  [{TODAY}]")

    # Load existing papers
    existing = {"last_updated": TODAY, "papers": []}
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)

    new_papers = []
    for category, queries in SEARCHES.items():
        print(f"\n▸ {category} (target: {DAILY_LIMIT} new papers)")
        collected = []
        for q in queries:
            if len(collected) >= DAILY_LIMIT:
                break
            print(f"  {q[:55]}...")
            fetched = fetch_ss(q, category, limit=DAILY_LIMIT * 2)
            collected.extend(fetched)
            collected = dedupe(collected)
            print(f"  → {len(fetched)} fetched, {len(collected)} unique so far")
        new_papers.extend(collected[:DAILY_LIMIT])
    print(f"\nNew papers collected today: {len(new_papers)}")

    # Merge: new first, then keep existing (preserves manual edits / ZH translations)
    merged = dedupe(new_papers + existing.get("papers", []))
    merged = sorted(merged, key=lambda p: p.get("date_added", ""), reverse=True)
    merged = merged[:MAX_PAPERS]

    output = {"last_updated": TODAY, "papers": merged}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Done. Total papers in file: {len(merged)}")


if __name__ == "__main__":
    main()
