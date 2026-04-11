#!/usr/bin/env python3
"""
FENG LAB — Daily Literature Fetcher
Searches Semantic Scholar for papers on configured topics.
Merges new findings into data/papers.json.
Auto-translates titles + abstracts via Gemini API.
"""

import json
import os
import sys
import time
import hashlib
import datetime
import requests
from pathlib import Path

# Windows UTF-8 fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TODAY = datetime.date.today().isoformat()
DATA_FILE  = Path(__file__).parent.parent / "data" / "papers.json"
MAX_PAPERS  = 300
DAILY_LIMIT = 2   # New papers per category per day

# ── Journal IF lookup ────────────────────────────────────────────────────────
JOURNAL_IF = {
    "british journal of sports medicine": "18.4",
    "bjsm": "18.4",
    "american journal of sports medicine": "5.5",
    "am j sports med": "5.5",
    "journal of orthopaedic": "6.8",
    "jospt": "6.8",
    "scandinavian journal of medicine": "5.2",
    "scand j med sci sports": "5.2",
    "journal of biomechanics": "2.8",
    "gait & posture": "2.5",
    "gait and posture": "2.5",
    "european journal of sport science": "3.5",
    "ejss": "3.5",
    "journal of strength and conditioning": "3.2",
    "journal of strength & conditioning": "3.2",
    "jscr": "3.2",
    "sports medicine": "9.8",
    "medicine & science in sports": "4.5",
    "medicine and science in sports": "4.5",
    "international journal of sports physiology": "3.8",
    "international journal of sport nutrition": "3.1",
}

def lookup_if(venue: str) -> str:
    v = venue.lower()
    for key, val in JOURNAL_IF.items():
        if key in v:
            return val
    return ""

# ── Search topics ─────────────────────────────────────────────────────────────
SEARCHES = {
    "biomechanics": [
        "gait biomechanics motion capture sports injury lower limb",
        "IMU inertial measurement unit human movement analysis running",
        "electromyography muscle activation sports performance biomechanics",
        "plantar pressure foot mechanics running gait",
        "movement phenotype injury risk sports biomechanics",
    ],
    "performance": [
        "rate of force development neuromuscular athletic performance",
        "sprint jump strength power sports performance training",
        "running economy fatigue resistance training athletes",
        "high intensity interval training sport performance adaptation",
    ],
    "supplements": [
        "creatine collagen caffeine sports supplement exercise RCT",
        "ergogenic aids sports nutrition randomized controlled trial",
        "nitrate beta-alanine sport performance supplementation",
        "protein intake muscle recovery exercise adaptation",
    ],
    "preprint": [
        "sports biomechanics running gait injury bioRxiv preprint 2024",
        "exercise performance neuromuscular training preprint medRxiv",
        "wearable sensor IMU motion analysis sports preprint",
    ],
}

SS_URL    = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = (
    "title,authors,year,abstract,externalIds,publicationDate,"
    "venue,isOpenAccess,openAccessPdf,citationCount"
)

# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_ss(query: str, category: str, limit: int = 6) -> list:
    papers = []
    try:
        params = {
            "query": query,
            "fields": SS_FIELDS,
            "limit": limit,
            "publicationDateOrYear": f"{datetime.date.today().year - 3}:",
        }
        r = requests.get(SS_URL, params=params, timeout=20)
        r.raise_for_status()

        for p in r.json().get("data", []):
            title    = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not title or not abstract or len(abstract) < 80:
                continue

            doi      = p.get("externalIds", {}).get("DOI", "")
            authors  = [a.get("name", "") for a in (p.get("authors") or [])[:5]]
            is_oa    = bool(p.get("isOpenAccess"))
            oa_pdf   = p.get("openAccessPdf") or {}
            pdf_url  = oa_pdf.get("url", "") if isinstance(oa_pdf, dict) else ""
            venue    = (p.get("venue") or "")
            citations = p.get("citationCount") or 0

            papers.append({
                "id": hashlib.md5((title + str(p.get("year", ""))).encode()).hexdigest()[:8],
                "title_en":       title,
                "title_zh":       "",
                "authors":        authors,
                "journal":        venue,
                "year":           (p.get("year") or datetime.date.today().year),
                "date_added":     TODAY,
                "category":       category,
                "doi":            doi,
                "impact_factor":  lookup_if(venue),
                "citation_count": citations,
                "is_open_access": is_oa,
                "pdf_url":        pdf_url,
                "abstract_en":    abstract[:900],
                "abstract_zh":    "",
                "keywords":       [],
            })

        time.sleep(1.2)
    except Exception as e:
        print(f"  [!] Error for '{query[:40]}': {e}")
    return papers


# ── Deduplication ─────────────────────────────────────────────────────────────
def dedupe(papers: list) -> list:
    seen, result = set(), []
    for p in papers:
        key = (p.get("doi") or "").strip() or p.get("title_en", "").lower()[:60]
        if key and key not in seen:
            seen.add(key)
            result.append(p)
    return result


# ── Gemini translation ────────────────────────────────────────────────────────
def translate_papers(papers: list) -> list:
    """Fill title_zh and abstract_zh for papers missing translations."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("  [!] GEMINI_API_KEY not set, skipping translation.")
        return papers

    to_translate = [p for p in papers if not p.get("title_zh") or not p.get("abstract_zh")]
    if not to_translate:
        print(f"  All papers already have translations.")
        return papers

    print(f"  Translating {len(to_translate)} papers via Gemini...")

    # Process in batches of 6 to stay within token limits
    BATCH = 6
    for start in range(0, len(to_translate), BATCH):
        batch = to_translate[start:start + BATCH]
        items = "\n\n".join([
            f"{i+1}. Title: {p['title_en']}\nAbstract: {p['abstract_en'][:600]}"
            for i, p in enumerate(batch)
        ])
        prompt = (
            f"Translate the following {len(batch)} academic paper titles and abstracts "
            f"into Chinese. Return ONLY a JSON array with {len(batch)} objects, "
            f'each with "title_zh" and "abstract_zh" fields. '
            f"Keep translations accurate and academic.\n\n{items}"
        )
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            resp = model.generate_content(prompt)
            raw = resp.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            translations = json.loads(raw.strip())
            for i, p in enumerate(batch):
                if i < len(translations):
                    p["title_zh"]    = translations[i].get("title_zh", "")
                    p["abstract_zh"] = translations[i].get("abstract_zh", "")
            print(f"    Batch {start//BATCH + 1}: {len(batch)} translated ✓")
        except Exception as e:
            print(f"    [!] Translation batch error: {e}")
        time.sleep(2)

    return papers


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"FENG LAB — Daily fetch  [{TODAY}]")

    existing = {"last_updated": TODAY, "papers": []}
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)

    existing_papers = existing.get("papers", [])

    # Fetch new papers
    new_papers = []
    for category, queries in SEARCHES.items():
        print(f"\n▸ {category} (target: {DAILY_LIMIT} new)")
        collected = []
        for q in queries:
            if len(collected) >= DAILY_LIMIT:
                break
            print(f"  {q[:60]}...")
            fetched = fetch_ss(q, category, limit=DAILY_LIMIT * 3)
            collected.extend(fetched)
            collected = dedupe(collected)
        new_papers.extend(collected[:DAILY_LIMIT])

    print(f"\nNew papers collected: {len(new_papers)}")

    # Translate new papers that are missing translations
    new_papers = translate_papers(new_papers)

    # Also backfill any existing papers still missing translation (up to 10 per run)
    needs_translation = [p for p in existing_papers if not p.get("title_zh") or not p.get("abstract_zh")][:10]
    if needs_translation:
        print(f"\nBackfilling {len(needs_translation)} existing papers...")
        needs_translation = translate_papers(needs_translation)

    # Merge
    merged = dedupe(new_papers + existing_papers)
    merged = sorted(merged, key=lambda p: p.get("date_added", ""), reverse=True)
    merged = merged[:MAX_PAPERS]

    output = {"last_updated": TODAY, "papers": merged}
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Done. Total papers: {len(merged)}")


if __name__ == "__main__":
    main()
