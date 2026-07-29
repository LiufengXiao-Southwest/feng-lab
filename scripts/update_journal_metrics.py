#!/usr/bin/env python3
"""
FENG LAB — Journal metrics updater.

Regenerates ``data/journals.json`` from three inputs, in descending order of
authority:

1. ``data/jcr_seed.json`` — hand-curated Clarivate JCR impact factors. JCR is
   proprietary and publishes once a year (June); there is no legal feed and
   nothing that changes daily. Only journals with a verified value belong here.
2. ``data/scimago_*.csv`` — SCImago snapshots (SJR, Scopus quartile, 2-year
   citations per document). Committed to the repo and refreshed once a year:
   scimagojr.com sits behind Cloudflare and reliably 403s CI runners, and SJR
   only updates annually anyway, so fetching it from Actions buys nothing.
3. **OpenAlex** — refreshed on every run for canonical names, ISSNs, aliases,
   publisher, h-index and OA status.

On why the displayed impact number is SCImago's Cit/Doc(2y) and not OpenAlex's
``2yr_mean_citedness``: measured against JCR 2024 across sports-science
journals, SCImago's rank correlation is 0.964 while OpenAlex's is 0.607.
OpenAlex counts conference abstracts in the denominator — Medicine & Science in
Sports & Exercise indexes ~48k abstracts alongside ~48k articles and scores
0.46 against a JCR IF of 3.9. Publishing that number would be worse than the
stale hardcoded table this replaced.

Usage::

    python scripts/update_journal_metrics.py            # refresh
    python scripts/update_journal_metrics.py --check    # report problems only

Data credit, required by SCImago's terms and rendered in the site footer:
SCImago, (n.d.). SJR — SCImago Journal & Country Rank [Portal]. Powered by Scopus.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from journal_metrics import normalize_issn, normalize_name  # noqa: E402

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
SEED_FILE = DATA / "jcr_seed.json"
ARCHIVE_FILE = DATA / "archive.json"
OUT_FILE = DATA / "journals.json"

# easyScholar is the primary impact-factor source: it returns the real JCR IF,
# the JCR quartile, and the CAS (中科院) tiers that Chinese readers actually use
# to judge a journal. Free key, queried by journal name.
EASYSCHOLAR = "https://www.easyscholar.cc/open/getPublicationRank"
EASYSCHOLAR_KEY = os.environ.get("EASYSCHOLAR_SECRET_KEY", "")

OPENALEX = "https://api.openalex.org/sources"
# OpenAlex moved to a credit system on 2026-02-13. Anonymous callers get $0.10
# a day, which a shared CI egress IP can burn through; a free key raises it to
# $1. Batched ISSN filters cost $0.0001 per call, so one run is ~$0.0005 either
# way — the key is cheap insurance, not a requirement.
OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY", "")
MAILTO = os.environ.get("CONTACT_EMAIL", "xiaofengliu2023@gmail.com")
HEADERS = {"User-Agent": f"feng-lab/1.0 (mailto:{MAILTO})"}

JCR_YEAR = "2024"   # edition easyScholar currently serves; bump each June
BATCH = 40          # ISSNs per OpenAlex request
SUSPECT_RATIO = 4.0  # curated IF this far from SCImago's Cit/Doc(2y) gets flagged

_CATEGORY_RE = re.compile(r"([^;()]+?)\s*\((Q[1-4])\)")
# Which Scopus category's quartile to show, most specific first.
_PREFERRED_CATEGORIES = (
    "orthopedics and sports medicine",
    "physical therapy, sports therapy and rehabilitation",
    "sports science",
    "physiology",
    "biomedical engineering",
    "nutrition and dietetics",
)


def topic_labels(src: dict, keep: int = 6) -> list[str]:
    """Flatten a source's OpenAlex topics into "field / subfield" strings.

    Used only to decide whether a journal with no JCR, CAS or SCImago entry is
    plausibly in this site's subject area. A photonics journal cleared the
    OpenAlex-only fallback purely on citation rate and reached a sports-science
    digest; nothing in the numbers could have caught that.
    """
    out: list[str] = []
    for t in (src.get("topics") or [])[:keep]:
        field = ((t.get("field") or {}).get("display_name") or "").strip()
        subfield = ((t.get("subfield") or {}).get("display_name") or "").strip()
        label = f"{field} / {subfield}".strip(" /")
        if label and label not in out:
            out.append(label)
    return out


def _num(raw: str) -> float:
    """SCImago exports use a comma as the decimal separator."""
    try:
        return float((raw or "0").replace(",", ".").strip() or 0)
    except ValueError:
        return 0.0


_SCIMAGO_CACHE: dict[str, dict] | None = None


def load_scimago(quiet: bool = False) -> dict[str, dict]:
    """Index every committed SCImago snapshot by ISSN.

    Memoized: resolve_live() calls this per journal, and re-parsing 600 CSV rows
    each time turned a cheap lookup into the slowest part of the fetch.
    """
    global _SCIMAGO_CACHE
    if _SCIMAGO_CACHE is not None:
        return _SCIMAGO_CACHE

    index: dict[str, dict] = {}
    files = sorted(DATA.glob("scimago_*.csv"))
    if not files:
        if not quiet:
            print("  [!] No data/scimago_*.csv snapshot found — SJR data unavailable.")
        _SCIMAGO_CACHE = index
        return index

    for path in files:
        rows = 0
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f, delimiter=";"):
                cats = dict(_CATEGORY_RE.findall(row.get("Categories") or ""))
                quartile = ""
                for want in _PREFERRED_CATEGORIES:
                    for name, q in cats.items():
                        if name.strip().lower() == want:
                            quartile = q
                            break
                    if quartile:
                        break
                # Column name differs between the full export ("SJR Best
                # Quartile") and a category-filtered one ("SJR Quartile").
                best_q = row.get("SJR Best Quartile") or row.get("SJR Quartile") or ""
                rec = {
                    "title": (row.get("Title") or "").strip(),
                    "sjr": round(_num(row.get("SJR")), 3),
                    "sjr_quartile": (quartile or best_q).strip(),
                    "sjr_categories": {k.strip(): v for k, v in cats.items()},
                    "cite_doc_2y": round(_num(row.get("Citations / Doc. (2years)")), 2),
                    "scimago_h": int(_num(row.get("H index"))),
                }
                for raw in (row.get("Issn") or "").replace(" ", "").split(","):
                    key = normalize_issn(raw)
                    if key:
                        index.setdefault(key, rec)
                rows += 1
        if not quiet:
            print(f"  · {path.name}: {rows} journals")
    _SCIMAGO_CACHE = index
    return index


def fetch_easyscholar(name: str) -> dict | None:
    """Look up one journal's JCR and CAS rankings by name.

    Returns the normalized subset the site displays, or None when the key is
    unset, the journal is unknown, or the request fails. Every caller must cope
    with None — a missing key must degrade to SCImago, never crash the build.
    """
    if not EASYSCHOLAR_KEY or not name:
        return None
    try:
        r = requests.get(
            EASYSCHOLAR,
            params={"secretKey": EASYSCHOLAR_KEY, "publicationName": name},
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError):
        return None

    if body.get("code") != 200:
        return None
    rank = ((body.get("data") or {}).get("officialRank") or {}).get("all") or {}
    if not rank:
        return None

    def clean(val: str) -> str:
        # easyScholar terminates the tier strings with a full-width period.
        return (val or "").strip().rstrip("。;； ")

    out = {
        "jcr_if": clean(rank.get("sciif")),
        "jcr_if5": clean(rank.get("sciif5")),
        "jcr_quartile": clean(rank.get("sci")),
        "jci": clean(rank.get("jci")),
        # 中科院分区: sciUp is the current "升级版" major-category tier,
        # sciUpSmall the sub-category tier, sciUpTop the TOP flag.
        "cas_tier": clean(rank.get("sciUp") or rank.get("sciBase")),
        "cas_tier_small": clean(rank.get("sciUpSmall")),
        "cas_top": clean(rank.get("sciUpTop")),
        "esi": clean(rank.get("esi")),
    }
    return {k: v for k, v in out.items() if v}


def _get(params: dict) -> dict | None:
    if OPENALEX_KEY:
        params = {**params, "api_key": OPENALEX_KEY}
    for attempt in range(3):
        try:
            r = requests.get(OPENALEX, params=params, headers=HEADERS, timeout=45)
            if r.status_code == 429:
                time.sleep(4 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                print(f"    [!] OpenAlex request failed: {e}")
            time.sleep(2 * (attempt + 1))
    return None


def fetch_openalex(issns: list[str]) -> dict[str, dict]:
    """Resolve ISSNs to OpenAlex sources, batched.

    One request per 40 ISSNs costs $0.0001. Per-journal `search=` lookups cost
    $0.001 each and match ghost entries (a 4-article duplicate of BJSM exists),
    so ISSN filtering is both cheaper and more accurate.
    """
    out: dict[str, dict] = {}
    for i in range(0, len(issns), BATCH):
        chunk = issns[i:i + BATCH]
        data = _get({
            "filter": "issn:" + "|".join(chunk),
            "per-page": 100,
            "select": ("id,display_name,alternate_titles,issn,issn_l,summary_stats,"
                       "works_count,type,host_organization_name,is_oa,is_in_doaj,"
                       "is_preprint_repository,topics"),
        })
        if not data:
            continue
        for src in data.get("results", []):
            for issn in src.get("issn") or []:
                key = normalize_issn(issn)
                if key:
                    out[key] = src
        print(f"    batch {i // BATCH + 1}: {len(chunk)} ISSNs → "
              f"{len(data.get('results', []))} sources "
              f"(cost ${data.get('meta', {}).get('cost_usd', 0)})")
        time.sleep(0.4)
    return out


def resolve_live(name: str, issns: list[str] | None = None) -> dict | None:
    """Resolve a single journal on demand, for venues the cache hasn't seen.

    The cache is built from journals the site has already published, so a paper
    from a journal that has never appeared before would be judged "unknown" and
    dropped — which is how the previous hardcoded table made it impossible for
    Nature, The Lancet or J Physiol to ever reach the digest. The fetcher calls
    this on a cache miss and feeds the result back into the index.
    """
    issns = [normalize_issn(i) for i in (issns or [])]
    issns = [i for i in issns if i]

    src = None
    if issns:
        found = fetch_openalex(issns)
        src = next((found[i] for i in issns if i in found), None)

    entry: dict = {"name": name, "issn": issns, "aliases": []}
    if src:
        stats = src.get("summary_stats") or {}
        entry["name"] = src.get("display_name") or name
        entry["aliases"] = [a for a in (src.get("alternate_titles") or []) if a]
        for i in [normalize_issn(src.get("issn_l") or "")] + \
                 [normalize_issn(x) for x in src.get("issn") or []]:
            if i and i not in entry["issn"]:
                entry["issn"].append(i)
        entry.update({
            "publisher": src.get("host_organization_name") or "",
            "openalex_2yr": round(float(stats.get("2yr_mean_citedness") or 0), 3),
            "h_index": stats.get("h_index") or 0,
            "works_count": src.get("works_count") or 0,
            "is_oa": bool(src.get("is_oa")),
            "in_doaj": bool(src.get("is_in_doaj")),
            "is_preprint_server": bool(src.get("is_preprint_repository")),
            "topics": topic_labels(src),
        })

    es = fetch_easyscholar(entry["name"]) or (fetch_easyscholar(name) if name != entry["name"] else None)
    if es:
        entry.update(es)
        entry["jcr_year"] = JCR_YEAR
        entry["if_provider"] = "easyscholar"

    scimago = load_scimago(quiet=True)
    sjr = next((scimago[i] for i in entry["issn"] if i in scimago), None)
    if sjr:
        entry.update({
            "sjr": sjr["sjr"],
            "sjr_quartile": sjr["sjr_quartile"],
            "sjr_categories": sjr["sjr_categories"],
            "cite_doc_2y": sjr["cite_doc_2y"],
        })

    has_metric = any(entry.get(k) for k in ("jcr_if", "cite_doc_2y", "openalex_2yr"))
    return entry if has_metric else None


def collect_targets() -> list[dict]:
    """Curated seed journals, plus every venue the site has ever published."""
    targets: list[dict] = []
    seen: set[str] = set()

    if SEED_FILE.exists():
        seed = json.loads(SEED_FILE.read_text(encoding="utf-8"))
        # alias_only entries carry no curated IF; they exist so venue-string
        # variants and abbreviations still resolve to the right journal.
        for j in [*seed.get("journals", []), *seed.get("alias_only", [])]:
            key = normalize_name(j.get("name", ""))
            if key and key not in seen:
                seen.add(key)
                targets.append(dict(j))

    if ARCHIVE_FILE.exists():
        archive = json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"))
        for papers in archive.get("dates", {}).values():
            for p in papers:
                venue = (p.get("journal") or "").strip()
                key = normalize_name(venue)
                if key and key not in seen:
                    seen.add(key)
                    entry = {"name": venue}
                    issn = (p.get("journal_issn") or "").strip()
                    if issn:
                        entry["issn"] = [issn]
                    targets.append(entry)
    return targets


def resolve_issns(targets: list[dict], scimago: dict[str, dict]) -> None:
    """Fill in each target's ISSN from the SCImago snapshot where missing."""
    by_name = {}
    for issn, rec in scimago.items():
        by_name.setdefault(normalize_name(rec["title"]), issn)

    for t in targets:
        if t.get("issn"):
            continue
        candidates = [t.get("name", "")] + list(t.get("aliases", []))
        for c in candidates:
            hit = by_name.get(normalize_name(c))
            if hit:
                t["issn"] = [hit]
                break


def build(check_only: bool = False) -> int:
    print("Loading SCImago snapshots...")
    scimago = load_scimago()
    print(f"  → {len(scimago)} ISSNs indexed\n")

    targets = collect_targets()
    resolve_issns(targets, scimago)
    known = sorted({normalize_issn(i) for t in targets for i in t.get("issn", [])} - {""})
    print(f"Resolving {len(targets)} journals ({len(known)} with a known ISSN) via OpenAlex...")
    openalex = fetch_openalex(known)
    print(f"  → {len(openalex)} ISSNs resolved\n")

    if EASYSCHOLAR_KEY:
        print("easyScholar key present — fetching live JCR / CAS rankings.")
    else:
        print("[!] EASYSCHOLAR_SECRET_KEY not set — falling back to curated seed + SCImago.")

    journals: list[dict] = []
    suspects: list[str] = []
    no_metrics: list[str] = []
    resolved_es = 0

    for t in targets:
        issns = [normalize_issn(i) for i in t.get("issn", [])]
        issns = [i for i in issns if i]
        src = next((openalex[i] for i in issns if i in openalex), None)
        sjr = next((scimago[i] for i in issns if i in scimago), None)

        entry: dict = {
            "name": (src or {}).get("display_name") or t.get("name", ""),
            "aliases": sorted({
                *(src or {}).get("alternate_titles", []),
                *t.get("aliases", []),
                t.get("name", ""),
            } - {(src or {}).get("display_name") or t.get("name", ""), ""}),
            "issn": issns,
        }

        if src:
            stats = src.get("summary_stats") or {}
            issn_l = normalize_issn(src.get("issn_l") or "")
            for i in [issn_l] + [normalize_issn(x) for x in src.get("issn") or []]:
                if i and i not in entry["issn"]:
                    entry["issn"].append(i)
            entry.update({
                "publisher": src.get("host_organization_name") or "",
                "openalex_id": (src.get("id") or "").rsplit("/", 1)[-1],
                "openalex_2yr": round(float(stats.get("2yr_mean_citedness") or 0), 3),
                "h_index": stats.get("h_index") or 0,
                "works_count": src.get("works_count") or 0,
                "is_oa": bool(src.get("is_oa")),
                "in_doaj": bool(src.get("is_in_doaj")),
                "is_preprint_server": bool(src.get("is_preprint_repository")),
                "topics": topic_labels(src),
            })

        if sjr:
            entry.update({
                "sjr": sjr["sjr"],
                "sjr_quartile": sjr["sjr_quartile"],
                "sjr_categories": sjr["sjr_categories"],
                "cite_doc_2y": sjr["cite_doc_2y"],
            })

        # easyScholar first (live JCR + CAS tiers), curated seed as fallback.
        es = None
        for candidate in [entry["name"], t.get("name", "")] + list(t.get("aliases", [])):
            if candidate:
                es = fetch_easyscholar(candidate)
                if es:
                    break
        if es:
            entry.update(es)
            entry["jcr_year"] = JCR_YEAR
            entry["if_provider"] = "easyscholar"
            resolved_es += 1
            time.sleep(0.25)
        elif t.get("jcr_if"):
            entry["jcr_if"] = t["jcr_if"]
            entry["jcr_year"] = t.get("jcr_year", "")
            entry["jcr_quartile"] = t.get("jcr_quartile", "")
            entry["if_provider"] = "curated"

        if entry.get("jcr_if") and sjr and sjr["cite_doc_2y"] > 0:
            try:
                ratio = float(entry["jcr_if"]) / sjr["cite_doc_2y"]
                if ratio > SUSPECT_RATIO or ratio < 1 / SUSPECT_RATIO:
                    suspects.append(
                        f"{entry['name']}: IF {entry['jcr_if']} vs "
                        f"SCImago Cit/Doc(2y) {sjr['cite_doc_2y']}"
                    )
            except (TypeError, ValueError):
                pass

        if not (entry.get("jcr_if") or entry.get("cite_doc_2y") or entry.get("openalex_2yr")):
            no_metrics.append(entry["name"])

        journals.append(entry)

    have_sjr = sum(1 for j in journals if j.get("cite_doc_2y"))
    have_jcr = sum(1 for j in journals if j.get("jcr_if"))
    have_cas = sum(1 for j in journals if j.get("cas_tier"))
    print(f"\nCoverage: {have_jcr}/{len(journals)} with an impact factor "
          f"({resolved_es} live from easyScholar), {have_cas} with a CAS tier, "
          f"{have_sjr} with SCImago, "
          f"{len(journals) - len(no_metrics)} with at least one metric.")

    if suspects:
        print(f"\n⚠ {len(suspects)} curated values that disagree sharply with SCImago:")
        for s in suspects:
            print(f"    {s}")
        print("  Verify these against JCR and correct data/jcr_seed.json.")

    if no_metrics:
        print(f"\n⚠ {len(no_metrics)} journals with no metric at all "
              f"(they will render without a badge):")
        for n in no_metrics[:12]:
            print(f"    {n}")

    if check_only:
        print("\n--check: nothing written.")
        return 1 if suspects else 0

    payload = {
        "updated": datetime.date.today().isoformat(),
        "jcr_year": JCR_YEAR,
        "sources": {
            "easyscholar": "easyscholar.cc — JCR impact factor, JCR quartile, CAS tiers; refreshed every run",
            "jcr_seed": "data/jcr_seed.json — curated fallback used only when easyScholar has no entry",
            "scimago": "data/scimago_*.csv — SCImago/Scopus snapshot, refreshed annually by hand",
            "openalex": "api.openalex.org — names, ISSNs, h-index, OA status; refreshed every run",
        },
        "attribution": ("SCImago, (n.d.). SJR — SCImago Journal & Country Rank "
                        "[Portal]. Powered by Scopus."),
        "count": len(journals),
        "journals": sorted(journals, key=lambda j: j["name"]),
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Wrote {OUT_FILE.relative_to(ROOT)} — {len(journals)} journals.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh data/journals.json")
    ap.add_argument("--check", action="store_true", help="report problems without writing")
    return build(check_only=ap.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
