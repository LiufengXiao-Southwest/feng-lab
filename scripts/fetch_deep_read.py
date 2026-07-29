#!/usr/bin/env python3
"""
FENG LAB — Daily Deep Read Auto-Generator
Picks the highest-cited unread paper from AJSM / BJSM / JOSPT / SJMSS (last 5 years),
then calls Claude API to generate structured bilingual reading content.

Requires: ANTHROPIC_API_KEY environment variable
"""

import json
import os
import sys
import time
import datetime
import requests
from pathlib import Path

# Windows UTF-8 fix
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TODAY     = datetime.date.today().isoformat()
YEAR_FROM = datetime.date.today().year - 5

ROOT                = Path(__file__).parent.parent
DEEP_READ_FILE      = ROOT / "data" / "deep_read.json"
HISTORY_FILE        = ROOT / "data" / "deep_read_history.json"
HISTORY_FULL_FILE   = ROOT / "data" / "deep_read_history_full.json"

# Target journals: query_name is used both to search SS and to match venue field.
# Impact factors are NOT stored here — they are resolved at runtime from
# data/journals.json, so this file cannot drift out of sync with the main
# fetcher the way the two hardcoded copies of the IF table used to.
JOURNALS = [
    {
        "query_name": "American Journal of Sports Medicine",
        "short": "AJSM",
        "venue_keywords": ["american journal of sports medicine", "am j sports med"],
    },
    {
        "query_name": "British Journal of Sports Medicine",
        "short": "BJSM",
        "venue_keywords": ["british journal of sports medicine", "br j sports med", "bjsm"],
    },
    {
        "query_name": "Journal of Orthopaedic & Sports Physical Therapy",
        "short": "JOSPT",
        "venue_keywords": ["journal of orthopaedic", "jospt", "sports physical therapy"],
    },
    {
        "query_name": "Scandinavian Journal of Medicine & Science in Sports",
        "short": "SJMSS",
        "venue_keywords": ["scandinavian journal", "scand j med sci sports"],
    },
]

sys.path.insert(0, str(Path(__file__).parent))
from journal_metrics import JournalIndex, display_impact, display_tier  # noqa: E402

JOURNAL_INDEX = JournalIndex.load()


def journal_metrics(journal: dict) -> tuple[str, str, str]:
    """Return (impact_factor, provenance, tier) for a target journal."""
    entry = JOURNAL_INDEX.lookup(journal["query_name"])
    if not entry:
        return "", "", ""
    value, source = display_impact(entry)
    return value, source, display_tier(entry)

SS_URL    = "https://api.semanticscholar.org/graph/v1/paper/search"
SS_FIELDS = (
    "title,authors,year,abstract,externalIds,venue,"
    "isOpenAccess,openAccessPdf,citationCount,publicationDate"
)

# ── Semantic Scholar helpers ──────────────────────────────────────────────────

def venue_matches(venue_str: str, keywords: list) -> bool:
    v = venue_str.lower()
    return any(kw in v for kw in keywords)


def fetch_for_journal(journal: dict, limit: int = 50) -> list:
    """Return papers from this journal sorted by citation count."""
    try:
        r = requests.get(SS_URL, params={
            "query": f'"{journal["query_name"]}" sports injury biomechanics rehabilitation',
            "fields": SS_FIELDS,
            "limit": limit,
            "publicationDateOrYear": f"{YEAR_FROM}:",
        }, timeout=25)
        r.raise_for_status()
        papers = r.json().get("data", [])
    except Exception as e:
        print(f"  [!] SS error for {journal['short']}: {e}")
        return []

    results = []
    for p in papers:
        year     = p.get("year") or 0
        abstract = (p.get("abstract") or "").strip()
        venue    = (p.get("venue") or "")
        if (year >= YEAR_FROM
                and len(abstract) > 100
                and venue_matches(venue, journal["venue_keywords"])):
            results.append(p)

    results.sort(key=lambda x: x.get("citationCount") or 0, reverse=True)
    return results


# ── History helpers ───────────────────────────────────────────────────────────

def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"used_dois": []}


def save_history(history: dict):
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Gemini API: generate structured reading ──────────────────────────────────

def generate_deep_read(paper: dict, journal: dict) -> dict:
    import google.generativeai as genai

    title     = paper.get("title", "")
    abstract  = paper.get("abstract", "")
    year      = paper.get("year", "")
    doi       = paper.get("externalIds", {}).get("DOI", "")
    citations = paper.get("citationCount", 0)
    authors_raw = [a.get("name", "") for a in (paper.get("authors") or [])[:6]]
    authors_str = ", ".join(authors_raw[:4]) + (" et al." if len(authors_raw) > 4 else "")

    prompt = f"""You are an expert sports scientist creating a structured bilingual deep-read for a Chinese sports science research lab (FENG LAB). The audience is Chinese sports biomechanics / rehabilitation researchers.

Paper details:
Title: {title}
Journal: {journal["query_name"]} ({journal["short"]}, IF {journal_metrics(journal)[0] or "n/a"})
Year: {year} | Citations: {citations}
Authors: {authors_str}
DOI: {doi}
Abstract:
{abstract}

Generate a JSON object ONLY (no markdown fences, no extra text) with this exact structure.
Be specific and accurate to this paper. Do NOT write generic placeholder text.

{{
  "title_zh": "<accurate Chinese translation of the title>",
  "sections": [
    {{
      "id": "why",
      "icon": "◎",
      "title_zh": "为什么值得读",
      "title_en": "Why It Matters",
      "content_zh": "<2-3 sentences: clinical/scientific significance specific to this paper, what gap it fills, why {citations} citations>",
      "content_en": "<same in English>"
    }},
    {{
      "id": "design",
      "icon": "⊞",
      "title_zh": "研究设计速览",
      "title_en": "Study Design",
      "content_zh": "<Use **bold** labels like **类型**、**样本**、**研究对象**、**主要结局**、**分析方法** etc. \\n between each line>",
      "content_en": "<Same with **bold** labels like **Type**、**Sample**、**Primary outcome**、**Analysis**. \\n between each line>"
    }},
    {{
      "id": "results",
      "icon": "◈",
      "title_zh": "核心数据",
      "title_en": "Key Numbers",
      "stats": [
        {{ "label_zh": "<metric name ZH>", "label_en": "<metric name EN>", "value": "<number + unit>", "note": "<p-value / CI / context if available>" }},
        {{ "label_zh": "...", "label_en": "...", "value": "...", "note": "..." }}
      ]
    }},
    {{
      "id": "appraisal",
      "icon": "◐",
      "title_zh": "方法学评价",
      "title_en": "Critical Appraisal",
      "pros_zh": ["<strength 1>", "<strength 2>", "<strength 3>"],
      "cons_zh": ["<limitation 1>", "<limitation 2>", "<limitation 3>"],
      "pros_en": ["<strength 1 EN>", "<strength 2 EN>", "<strength 3 EN>"],
      "cons_en": ["<limitation 1 EN>", "<limitation 2 EN>", "<limitation 3 EN>"]
    }},
    {{
      "id": "takeaway",
      "icon": "◆",
      "title_zh": "研究启示",
      "title_en": "Takeaway",
      "content_zh": "<3-4 numbered points using **bold** headings. Include one point connecting to biomechanics instrumentation (IMU/sEMG/plantar pressure/motion capture) if relevant. \\n\\n between points>",
      "content_en": "<same 3-4 points in English. \\n\\n between points>"
    }}
  ]
}}"""

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")

    # Gemini returns transient 500s often enough that a single unretried call
    # was failing the whole daily run.
    response = None
    delay = 5.0
    for attempt in range(4):
        try:
            response = model.generate_content(prompt)
            break
        except Exception as e:                       # noqa: BLE001
            if attempt == 3:
                raise
            print(f"    [!] Gemini error ({type(e).__name__}), "
                  f"retrying in {delay:.0f}s: {str(e)[:80]}")
            time.sleep(delay)
            delay *= 2

    raw = response.text.strip()
    # Strip accidental code fences
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"FENG LAB — Daily Deep Read  [{TODAY}]")

    # Skip if already updated today
    if DEEP_READ_FILE.exists():
        try:
            existing = json.loads(DEEP_READ_FILE.read_text(encoding="utf-8"))
            if existing.get("date") == TODAY:
                print("✓ deep_read.json already up to date for today. Skipping.")
                return
        except Exception:
            pass

    history = load_history()
    used_dois = set(history.get("used_dois", []))

    # Gather candidates from all journals
    all_candidates = []  # list of (paper_dict, journal_dict)
    for j in JOURNALS:
        print(f"  Searching {j['short']}...")
        papers = fetch_for_journal(j, limit=50)
        print(f"    → {len(papers)} matching papers")
        for p in papers[:15]:
            all_candidates.append((p, j))
        time.sleep(1.2)

    if not all_candidates:
        print("  [!] No candidates found from any journal. Aborting.")
        return

    # Sort all by citation count, pick first not in history
    all_candidates.sort(key=lambda x: x[0].get("citationCount") or 0, reverse=True)

    selected_paper = None
    selected_journal = None
    selected_doi = ""

    for paper, journal in all_candidates:
        doi = paper.get("externalIds", {}).get("DOI", "")
        if doi and doi in used_dois:
            continue
        selected_paper  = paper
        selected_journal = journal
        selected_doi    = doi
        break

    # Fallback: if all have been used, pick the highest-cited one anyway
    if not selected_paper:
        print("  [!] All candidates already in history — resetting and picking top paper.")
        selected_paper, selected_journal = all_candidates[0]
        selected_doi = selected_paper.get("externalIds", {}).get("DOI", "")

    citations = selected_paper.get("citationCount", 0)
    title     = selected_paper.get("title", "")
    year      = selected_paper.get("year", "")
    print(f"  Selected ({selected_journal['short']}, {year}, {citations} citations):")
    print(f"    {title[:80]}...")

    # Generate structured reading via Claude
    print("  Calling Claude API...")
    generated = generate_deep_read(selected_paper, selected_journal)

    # Build output
    authors_raw = [a.get("name", "") for a in (selected_paper.get("authors") or [])[:6]]
    authors_str = ", ".join(authors_raw[:4]) + (" et al." if len(authors_raw) > 4 else "")

    is_oa  = bool(selected_paper.get("isOpenAccess"))
    oa_pdf = selected_paper.get("openAccessPdf") or {}
    pdf_url = (oa_pdf.get("url", "") if isinstance(oa_pdf, dict) else "")

    if_value, if_source, tier = journal_metrics(selected_journal)

    output = {
        "date":           TODAY,
        "title_en":       title,
        "title_zh":       generated.get("title_zh", ""),
        "authors":        authors_str,
        "journal":        selected_journal["query_name"],
        "year":           year,
        "volume_page":    "",
        "doi":            selected_doi,
        "impact_factor":  if_value,
        "if_source":      if_source,
        "journal_tier":   tier,
        "is_open_access": is_oa,
        "pdf_url":        pdf_url,
        "category":       "biomechanics",
        "citation_count": citations,
        "sections":       generated.get("sections", []),
    }

    DEEP_READ_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  ✓ deep_read.json updated.")

    # Save history (keep last 90 to avoid recycling too quickly)
    if selected_doi:
        history.setdefault("used_dois", []).append(selected_doi)
        history["used_dois"] = history["used_dois"][-90:]
        save_history(history)

    # Save full entry to history_full.json (keeps last 60 entries for archive page)
    try:
        if HISTORY_FULL_FILE.exists():
            full_history = json.loads(HISTORY_FULL_FILE.read_text(encoding="utf-8"))
        else:
            full_history = {"entries": []}

        entries = full_history.get("entries", [])
        # Avoid duplicate dates
        entries = [e for e in entries if e.get("date") != TODAY]
        # Store a summary entry (no full sections to keep file small)
        summary = {
            "date":           TODAY,
            "title_en":       output["title_en"],
            "title_zh":       output["title_zh"],
            "authors":        output["authors"],
            "journal":        output["journal"],
            "year":           output["year"],
            "doi":            output["doi"],
            "impact_factor":  output["impact_factor"],
            "if_source":      output["if_source"],
            "journal_tier":   output["journal_tier"],
            "is_open_access": output["is_open_access"],
            "citation_count": output.get("citation_count", 0),
        }
        entries.insert(0, summary)
        entries = entries[:60]  # Keep last 60 entries
        full_history["entries"] = entries
        HISTORY_FULL_FILE.write_text(
            json.dumps(full_history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  ✓ deep_read_history_full.json updated ({len(entries)} entries).")
    except Exception as e:
        print(f"  [!] Could not update history_full: {e}")

    print(f"✓ Done.")


if __name__ == "__main__":
    main()
