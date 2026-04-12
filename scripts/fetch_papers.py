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

# ── JCR Q1 Journals (IF >= 3.0) ──────────────────────────────────────────────
# Key = lowercase substring to match venue string; Value = IF
# Only journals confirmed as JCR Q1 in their primary sport-science category
# with IF >= 3.0 are listed here. Papers not matching this list are discarded
# (exception: "preprint" category is exempt from this filter).
Q1_JOURNALS = {
    # ── Sports Medicine / General ───────────────────────────────────────────
    "british journal of sports medicine":        "18.4",
    "bjsm":                                       "18.4",
    "journal of sport and health science":        "13.8",
    "sports medicine":                            "9.8",   # matches "Sports Medicine" & "Sports Medicine - Open"
    "american journal of sports medicine":        "5.5",
    "am j sports med":                            "5.5",
    "scandinavian journal of medicine & science": "5.2",
    "scandinavian journal of medicine and science": "5.2",
    "scand j med sci sports":                     "5.2",
    "medicine & science in sports":               "4.5",
    "medicine and science in sports":             "4.5",
    "msse":                                       "4.5",
    "journal of orthopaedic & sports physical":   "6.8",
    "journal of orthopaedic and sports physical": "6.8",
    "jospt":                                      "6.8",
    "international journal of sports physiology": "3.8",
    "ijspp":                                      "3.8",
    "european journal of sport science":          "3.5",
    "physical therapy in sport":                  "3.5",
    "knee surgery, sports traumatology":          "3.5",
    "knee surgery sports traumatology":           "3.5",
    "journal of strength and conditioning":       "3.2",
    "journal of strength & conditioning":         "3.2",
    "jscr":                                       "3.2",
    "international journal of sport nutrition":   "3.1",
    "journal of sports sciences":                 "3.0",
    "journal of athletic training":               "3.0",
    # ── Rehabilitation / Orthopedics ────────────────────────────────────────
    "american journal of physical medicine":      "4.2",
    "physical therapy":                           "4.3",
    "journal of physiotherapy":                   "8.0",
    "clinical rehabilitation":                    "3.6",
    "disability and rehabilitation":              "3.2",
    "pm&r":                                       "3.3",
    # ── Biomechanics ────────────────────────────────────────────────────────
    "journal of biomechanics":                    "2.8",   # Q1 in Biomedical Engineering
    "gait & posture":                             "2.5",   # Q1 in Orthopedics
    "gait and posture":                           "2.5",
    "journal of neuroengineering and rehabilitation": "5.5",
    "frontiers in bioengineering and biotechnology": "4.3",
    # ── Nutrition / Physiology ──────────────────────────────────────────────
    "nutrients":                                  "4.8",
    "nutrients (mdpi)":                           "4.8",
    "applied physiology, nutrition":              "3.2",
    "applied physiology nutrition":               "3.2",
    "european journal of applied physiology":     "3.3",
    "international journal of environmental research and public health": "3.4",
}

MIN_IF = 3.0   # Hard minimum impact factor

# Journals that are JCR Q1 in their specific niche category but have IF < MIN_IF.
# These bypass the MIN_IF threshold check.
FIELD_Q1_WHITELIST = {
    "journal of biomechanics",   # Q1 in Biomedical Engineering / Biophysics
    "gait & posture",            # Q1 in Orthopedics
    "gait and posture",
}

def lookup_q1(venue: str):
    """Return (if_str, is_q1) for a venue string.
    is_q1=True if:
      - venue matches a Q1_JOURNALS entry with IF >= MIN_IF, OR
      - venue matches a FIELD_Q1_WHITELIST entry (category-specific Q1, IF < MIN_IF)
    """
    v = venue.lower()
    for key, if_val in Q1_JOURNALS.items():
        if key in v:
            in_whitelist = any(w in v for w in FIELD_Q1_WHITELIST)
            passes_if    = float(if_val) >= MIN_IF
            return if_val, passes_if or in_whitelist
    return "", False

# ── Search topics ─────────────────────────────────────────────────────────────
# Queries include journal names to bias Semantic Scholar toward Q1 sources.
# Non-preprint results are further filtered by Q1_JOURNALS + MIN_IF at runtime.
SEARCHES = {
    "biomechanics": [
        "gait biomechanics sports injury lower limb Journal of Biomechanics",
        "IMU inertial measurement unit running biomechanics Journal of Sports Sciences",
        "electromyography muscle activation sports biomechanics Medicine Science Sports Exercise",
        "plantar pressure foot mechanics gait running British Journal of Sports Medicine",
        "motion capture movement analysis sports injury Scandinavian Journal Medicine Science Sports",
    ],
    "performance": [
        "rate of force development neuromuscular athletic performance Medicine Science Sports Exercise",
        "sprint jump strength power training Sports Medicine",
        "running economy fatigue resistance training Journal Strength Conditioning Research",
        "high intensity interval training sport performance International Journal Sports Physiology",
        "aerobic capacity VO2max endurance athletes Scandinavian Journal Medicine Science Sports",
    ],
    "supplements": [
        "creatine caffeine sports supplement randomized controlled trial Journal Strength Conditioning",
        "ergogenic aids sports nutrition randomized trial Medicine Science Sports Exercise",
        "nitrate beta-alanine sport performance supplementation International Journal Sport Nutrition",
        "protein intake muscle recovery resistance exercise European Journal Applied Physiology",
        "collagen peptide joint recovery tendon supplement British Journal Sports Medicine",
    ],
    "preprint": [
        # Preprints are exempt from Q1/IF filter — search bioRxiv/medRxiv
        "sports biomechanics running gait injury bioRxiv preprint",
        "exercise performance neuromuscular training medRxiv preprint",
        "wearable sensor IMU motion analysis sports preprint",
    ],
}

SS_URL    = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = (
    "title,authors,year,abstract,externalIds,publicationDate,"
    "venue,isOpenAccess,openAccessPdf,citationCount"
)

# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_ss(query: str, category: str, limit: int = 10) -> list:
    """Fetch papers from Semantic Scholar.
    For non-preprint categories, only papers from JCR Q1 journals (IF >= MIN_IF)
    are kept.  Preprint papers are passed through without journal filtering.
    """
    papers = []
    is_preprint = (category == "preprint")

    try:
        params = {
            "query": query,
            "fields": SS_FIELDS,
            "limit": limit,
            "publicationDateOrYear": f"{datetime.date.today().year - 3}:",
        }
        r = requests.get(SS_URL, params=params, timeout=20)
        r.raise_for_status()

        accepted = rejected_if = rejected_abs = 0

        for p in r.json().get("data", []):
            title    = (p.get("title") or "").strip()
            abstract = (p.get("abstract") or "").strip()
            if not title or not abstract or len(abstract) < 80:
                rejected_abs += 1
                continue

            venue    = (p.get("venue") or "").strip()
            if_val, is_q1 = lookup_q1(venue)

            # ── Quality gate (non-preprint only) ─────────────────────────────
            if not is_preprint:
                if not is_q1:
                    rejected_if += 1
                    continue   # skip: not in Q1 journal list or IF < 3

            doi      = p.get("externalIds", {}).get("DOI", "")
            authors  = [a.get("name", "") for a in (p.get("authors") or [])[:5]]
            is_oa    = bool(p.get("isOpenAccess"))
            oa_pdf   = p.get("openAccessPdf") or {}
            pdf_url  = oa_pdf.get("url", "") if isinstance(oa_pdf, dict) else ""
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
                "impact_factor":  if_val,
                "citation_count": citations,
                "is_open_access": is_oa,
                "pdf_url":        pdf_url,
                "abstract_en":    abstract[:900],
                "abstract_zh":    "",
                "keywords":       [],
            })
            accepted += 1

        if not is_preprint:
            print(f"    accepted={accepted}, rejected(IF/Q1)={rejected_if}, rejected(no abs)={rejected_abs}")
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
            model = genai.GenerativeModel("gemini-2.5-flash-preview-04-17")
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
    # Use larger per-query limit (15) because Q1 filtering discards many results
    new_papers = []
    for category, queries in SEARCHES.items():
        print(f"\n▸ {category} (target: {DAILY_LIMIT} new, Q1/IF≥{MIN_IF} filter: {'off' if category == 'preprint' else 'on'})")
        collected = []
        for q in queries:
            if len(collected) >= DAILY_LIMIT:
                break
            print(f"  query: {q[:65]}...")
            fetched = fetch_ss(q, category, limit=15)
            collected.extend(fetched)
            collected = dedupe(collected)
        new_papers.extend(collected[:DAILY_LIMIT])
        print(f"  → {min(len(collected), DAILY_LIMIT)} paper(s) selected for {category}")

    print(f"\nNew papers collected: {len(new_papers)}")

    # Translate new papers that are missing translations
    new_papers = translate_papers(new_papers)

    # Also backfill any existing papers still missing translation (up to 10 per run)
    needs_translation = [p for p in existing_papers if not p.get("title_zh") or not p.get("abstract_zh")][:25]
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
