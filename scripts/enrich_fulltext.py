#!/usr/bin/env python3
"""
FENG LAB — Resolve legal open-access full text for each paper.

Semantic Scholar's ``openAccessPdf`` misses a lot. This walks a cascade of free,
official APIs and records the best legal route to the full text, so a reader can
tell from the card whether a paper is one click away or paywalled.

Cascade, in order (first hit wins):

1. **Europe PMC** — the only free source of *structured* full text (JATS XML with
   sections, figure captions, references). Best possible outcome for biomedical
   work, and what the deep-read pipeline should consume.
2. **Unpaywall** — the authoritative OA index. Free, 100k requests/day, but the
   ``email`` parameter must be a real address or it returns HTTP 422.
3. **OpenAlex** — OA locations, as a second opinion when Unpaywall has no record.
4. **Semantic Scholar** ``openAccessPdf`` — whatever the fetcher already found.
5. **DOI landing page** — always available, never a full text. Recorded as
   ``doi`` so the UI can show "只有摘要" honestly rather than a dead PDF button.

Anything paywalled stops at step 5. This script deliberately contains no
Sci-Hub, LibGen or proxy route: the output is published to a public website, and
those sources have no business in it. Fetching a paywalled paper for personal
reading through an institutional login is a separate, local concern.

Usage::

    python scripts/enrich_fulltext.py                 # today's papers
    python scripts/enrich_fulltext.py --all           # whole archive (slow)
    python scripts/enrich_fulltext.py --limit 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# Unpaywall rejects placeholder addresses outright, so this must be real.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
HEADERS = {"User-Agent": f"feng-lab/1.0 (mailto:{CONTACT_EMAIL or 'unset'})"}

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UNPAYWALL = "https://api.unpaywall.org/v2/"
OPENALEX_WORKS = "https://api.openalex.org/works/doi:"

# Ordered best-to-worst; the UI colours the button by this.
FULLTEXT_LABELS = {
    "pmc_xml": "全文 (结构化)",
    "pmc": "全文 (PMC)",
    "oa_pdf": "PDF 全文",
    "oa_html": "HTML 全文",
    "preprint": "预印本全文",
    "doi": "仅摘要",
}


def _json(url: str, params: dict | None = None, timeout: int = 25):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def try_europe_pmc(doi: str) -> dict | None:
    """Structured JATS full text, when the paper is in PMC's OA subset."""
    data = _json(EUROPE_PMC, {
        "query": f'DOI:"{doi}"',
        "format": "json",
        "resultType": "core",
    })
    if not data:
        return None
    results = (data.get("resultList") or {}).get("result") or []
    if not results:
        return None

    rec = results[0]
    pmcid = rec.get("pmcid") or ""
    full_ids = (rec.get("fullTextIdList") or {}).get("fullTextId") or []
    if pmcid and full_ids:
        return {
            "fulltext_url": f"https://europepmc.org/article/PMC/{pmcid}",
            "fulltext_type": "pmc_xml",
            "pmcid": pmcid,
            "pmid": rec.get("pmid", ""),
            "fulltext_xml": (
                f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
            ),
        }
    if pmcid:
        return {
            "fulltext_url": f"https://europepmc.org/article/PMC/{pmcid}",
            "fulltext_type": "pmc",
            "pmcid": pmcid,
            "pmid": rec.get("pmid", ""),
        }
    return {"pmid": rec.get("pmid", "")} if rec.get("pmid") else None


def try_unpaywall(doi: str) -> dict | None:
    if not CONTACT_EMAIL:
        return None
    data = _json(f"{UNPAYWALL}{doi}", {"email": CONTACT_EMAIL})
    if not data or not data.get("is_oa"):
        return None
    best = data.get("best_oa_location") or {}
    pdf = best.get("url_for_pdf")
    landing = best.get("url")
    if pdf:
        return {"fulltext_url": pdf, "fulltext_type": "oa_pdf",
                "oa_license": best.get("license") or ""}
    if landing:
        return {"fulltext_url": landing, "fulltext_type": "oa_html",
                "oa_license": best.get("license") or ""}
    return None


def try_openalex(doi: str) -> dict | None:
    data = _json(f"{OPENALEX_WORKS}{doi}", {"select": "open_access,best_oa_location"})
    if not data:
        return None
    best = data.get("best_oa_location") or {}
    oa = data.get("open_access") or {}
    url = best.get("pdf_url") or oa.get("oa_url")
    if not url:
        return None
    return {
        "fulltext_url": url,
        "fulltext_type": "oa_pdf" if best.get("pdf_url") else "oa_html",
        "oa_license": best.get("license") or "",
    }


def resolve(paper: dict) -> bool:
    """Fill full-text fields on one paper. Returns True if anything changed."""
    doi = (paper.get("doi") or "").strip()
    before = (paper.get("fulltext_url"), paper.get("fulltext_type"))

    found: dict = {}
    if doi:
        for step in (try_europe_pmc, try_unpaywall, try_openalex):
            hit = step(doi)
            if hit:
                found.update({k: v for k, v in hit.items() if v and k not in found})
                if found.get("fulltext_url"):
                    break
            time.sleep(0.35)

    # Fall back to what the fetcher already had, then to the DOI landing page.
    if not found.get("fulltext_url") and paper.get("pdf_url"):
        found["fulltext_url"] = paper["pdf_url"]
        found["fulltext_type"] = "oa_pdf"
    if not found.get("fulltext_url") and doi:
        found["fulltext_url"] = f"https://doi.org/{doi}"
        found["fulltext_type"] = "doi"

    if found.get("fulltext_type"):
        found["fulltext_label"] = FULLTEXT_LABELS.get(found["fulltext_type"], "")

    paper.update(found)
    return before != (paper.get("fulltext_url"), paper.get("fulltext_type"))


def collect(payload) -> list[dict]:
    """Every paper-shaped dict inside an already-parsed payload.

    Takes the parsed object rather than a path on purpose: callers mutate the
    returned dicts in place and then write `payload` back out, so both must be
    views of the same object. Parsing the file a second time here would hand
    back references into a throwaway copy and silently discard every edit.
    """
    out: list[dict] = []

    def walk(obj):
        if isinstance(obj, dict):
            if "title_en" in obj and ("doi" in obj or "journal" in obj):
                out.append(obj)
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)
    return out


def process(path: Path, limit: int | None, force: bool) -> int:
    payload_path = path
    if not payload_path.exists():
        return 0
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    papers = collect(payload)

    todo = [p for p in papers if force or not p.get("fulltext_type")]
    if limit:
        todo = todo[:limit]
    if not todo:
        print(f"  {path.name:28} nothing to do ({len(papers)} papers already resolved)")
        return 0

    print(f"  {path.name:28} resolving {len(todo)} of {len(papers)} papers...")
    changed = 0
    stats: dict[str, int] = {}
    for i, paper in enumerate(todo, 1):
        if resolve(paper):
            changed += 1
        stats[paper.get("fulltext_type", "none")] = stats.get(paper.get("fulltext_type", "none"), 0) + 1
        if i % 20 == 0:
            print(f"      {i}/{len(todo)}")

    if changed:
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.items()))
    print(f"      → {changed} updated  [{summary}]")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve open-access full text")
    ap.add_argument("--all", action="store_true", help="include the whole archive")
    ap.add_argument("--limit", type=int, default=None, help="cap papers per file")
    ap.add_argument("--force", action="store_true", help="re-resolve already-resolved papers")
    args = ap.parse_args()

    if not CONTACT_EMAIL:
        print("[!] CONTACT_EMAIL not set — Unpaywall will be skipped.")
        print("    Unpaywall requires a real address; a placeholder returns HTTP 422.")

    files = ["papers.json", "deep_read.json"]
    if args.all:
        files.append("archive.json")

    total = 0
    for name in files:
        total += process(DATA / name, args.limit, args.force)
    print(f"\n✓ {total} papers updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
