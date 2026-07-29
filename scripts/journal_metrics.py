#!/usr/bin/env python3
"""
FENG LAB — Journal metrics lookup.

Resolves a paper's venue (ISSN and/or venue string) to journal-level metrics
read from ``data/journals.json``, which is refreshed automatically by
``scripts/update_journal_metrics.py``.

Two things this module exists to prevent, both of which broke the old
hardcoded dict in fetch_papers.py:

1. Substring collisions. The old lookup returned the first dict key contained
   in the venue string, so "International Journal of Sports Medicine" (IF ~2.3)
   matched the key "sports medicine" and was published as IF 9.8. Matching here
   is exact-on-normalized-name first, and only falls back to substring with a
   longest-key-wins rule.
2. Silent discards. The old lookup treated "not in my dict" as "not Q1", so
   every journal outside the 40 hardcoded entries was thrown away — Nature,
   The Lancet, J Physiol and friends included. Coverage now comes from the
   generated cache, which carries thousands of journals.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Iterable

DATA_FILE = Path(__file__).parent.parent / "data" / "journals.json"

# Leading articles and punctuation carry no signal and differ between the
# Semantic Scholar venue string and the OpenAlex/Scimago display name.
_ARTICLE_RE = re.compile(r"^(the|a|an)\s+")
_NOISE_RE = re.compile(r"[^a-z0-9&\s]")
_SPACE_RE = re.compile(r"\s+")

# Expanded before matching so "Br J Sports Med" and "British Journal of Sports
# Medicine" normalize to the same string.
_ABBREV = {
    "j": "journal",
    "int": "international",
    "am": "american",
    "br": "british",
    "eur": "european",
    "scand": "scandinavian",
    "med": "medicine",
    "sci": "science",
    "phys": "physical",
    "ther": "therapy",
    "res": "research",
    "exerc": "exercise",
    "physiol": "physiology",
    "nutr": "nutrition",
    "orthop": "orthopaedic",
    "rehabil": "rehabilitation",
    "biomech": "biomechanics",
    "clin": "clinical",
    "appl": "applied",
}

# Dropped entirely: abbreviated venue strings omit connectors ("Br J Sports Med"
# vs "British Journal of Sports Medicine"), so keeping them makes the two forms
# irreconcilable. Removing them from both sides is what makes abbreviations
# resolve at all.
_STOPWORDS = {"of", "the", "a", "an", "in", "on", "for", "and"}


def normalize_name(name: str) -> str:
    """Fold a venue string into a comparable key."""
    if not name:
        return ""
    # Semantic Scholar venue strings arrive HTML-escaped often enough that
    # "Molecular &amp; Cellular Biomechanics" would otherwise never match.
    s = html.unescape(name).lower().strip()
    s = _NOISE_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    s = _ARTICLE_RE.sub("", s)
    s = s.replace("&", " and ")
    tokens = (_ABBREV.get(tok, tok) for tok in s.split())
    return " ".join(t for t in tokens if t not in _STOPWORDS).strip()


def normalize_issn(issn: str) -> str:
    """Uppercase, hyphenated ISSN; empty string if it isn't one."""
    if not issn:
        return ""
    s = re.sub(r"[^0-9xX]", "", issn).upper()
    if len(s) != 8:
        return ""
    return f"{s[:4]}-{s[4:]}"


class JournalIndex:
    """Lookup over the generated journals.json cache."""

    def __init__(self, payload: dict | None = None):
        payload = payload or {}
        self.updated = payload.get("updated", "")
        self.source = payload.get("source", "")
        self.payload = payload
        self.journals: list[dict] = list(payload.get("journals", []))
        # Venues no source could resolve. Remembered across runs so a
        # conference proceeding or predatory title is not re-queried daily.
        self.unresolved: set[str] = {
            normalize_name(v) for v in payload.get("unresolved", []) if v
        }
        self._by_issn: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        # Longest normalized name first, so "international journal of sports
        # medicine" is tested before "sports medicine".
        self._substr: list[tuple[str, dict]] = []

        for entry in payload.get("journals", []):
            for issn in entry.get("issn", []):
                key = normalize_issn(issn)
                if key:
                    self._by_issn.setdefault(key, entry)
            for name in [entry.get("name", "")] + list(entry.get("aliases", [])):
                key = normalize_name(name)
                if key:
                    self._by_name.setdefault(key, entry)
                    self._substr.append((key, entry))

        self._substr.sort(key=lambda kv: len(kv[0]), reverse=True)

    def __len__(self) -> int:
        return len(self._by_name)

    def add(self, entry: dict) -> None:
        """Index a journal discovered at runtime.

        The cache only knows journals the site has already published, so a
        brand-new venue would otherwise be judged 'unknown' and dropped. The
        fetcher resolves misses live and feeds them back through here.
        """
        if not entry or not entry.get("name"):
            return
        self.journals.append(entry)
        for issn in entry.get("issn", []):
            key = normalize_issn(issn)
            if key:
                self._by_issn.setdefault(key, entry)
        for name in [entry["name"]] + list(entry.get("aliases", [])):
            key = normalize_name(name)
            if key:
                self._by_name.setdefault(key, entry)
                self._substr.append((key, entry))
        self._substr.sort(key=lambda kv: len(kv[0]), reverse=True)

    @classmethod
    def load(cls, path: Path = DATA_FILE) -> "JournalIndex":
        if not path.exists():
            return cls({})
        try:
            with open(path, "r", encoding="utf-8") as f:
                return cls(json.load(f))
        except (OSError, json.JSONDecodeError):
            return cls({})

    def lookup(self, venue: str = "", issns: Iterable[str] = ()) -> dict | None:
        """Resolve a venue to its metrics entry.

        ISSN wins over name: it is unambiguous, and Semantic Scholar's venue
        strings are inconsistent ("Sports Medicine" vs "Sports medicine (Auckland,
        N.Z.)"). Falls back to exact normalized name, then to the longest
        substring match so partial venue strings still resolve.
        """
        for issn in issns or ():
            key = normalize_issn(issn)
            if key and key in self._by_issn:
                return self._by_issn[key]

        key = normalize_name(venue)
        if not key:
            return None
        if key in self._by_name:
            return self._by_name[key]

        # Longest-first: require the cached name to be a whole-word span of the
        # venue, so "sports medicine" no longer swallows unrelated journals
        # unless nothing more specific matched.
        for cached, entry in self._substr:
            if len(cached) < 12:
                continue  # too short to be a safe substring signal
            if re.search(rf"(^|\s){re.escape(cached)}($|\s)", key):
                return entry
        return None

    def mark_unresolved(self, venue: str) -> None:
        key = normalize_name(venue)
        if key:
            self.unresolved.add(key)

    def is_unresolved(self, venue: str) -> bool:
        key = normalize_name(venue)
        return bool(key) and key in self.unresolved

    def save(self, path: Path = DATA_FILE) -> None:
        """Persist the index, including anything added at runtime."""
        payload = dict(self.payload)
        payload["count"] = len(self.journals)
        payload["journals"] = sorted(self.journals, key=lambda j: j.get("name", ""))
        # Capped: this is a cache, not a ledger, and a journal that gains an
        # ISSN later should get another chance rather than being blocked forever.
        payload["unresolved"] = sorted(self.unresolved)[:500]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def impact_value(entry: dict | None) -> float:
    """Best available impact number for ranking.

    Order matches display_impact: real JCR first, then SCImago's 2-year
    citations per document (rank correlation with JCR ~0.96), then OpenAlex's
    2-year mean citedness (~0.61, and depressed for journals that index a lot
    of conference abstracts) as a last resort.
    """
    if not entry:
        return 0.0
    for field in ("jcr_if", "cite_doc_2y", "openalex_2yr"):
        try:
            val = float(entry.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return 0.0


def display_impact(entry: dict | None) -> tuple[str, str]:
    """Return (value, provenance label) for the card badge.

    The label is rendered in the UI so a SCImago- or OpenAlex-derived number is
    never mistaken for a Clarivate impact factor. Only the first branch is an
    actual impact factor; the others are labelled as what they are.
    """
    if not entry:
        return "", ""
    jcr = entry.get("jcr_if")
    if jcr:
        return str(jcr), f"JCR {entry.get('jcr_year', '')}".strip()
    cite = entry.get("cite_doc_2y")
    if cite:
        return f"{float(cite):.1f}", "SJR 2年篇均被引"
    oa = entry.get("openalex_2yr")
    if oa:
        return f"{float(oa):.1f}", "OpenAlex 2年均被引"
    return "", ""


def display_tier(entry: dict | None) -> str:
    """Chinese-facing journal tier: CAS sub-category first, then JCR quartile.

    Sports-science readers here rank journals by 中科院分区 far more than by
    quartile, so the sub-category tier (e.g. 运动科学1区) leads when present.
    """
    if not entry:
        return ""
    for field in ("cas_tier_small", "cas_tier"):
        val = (entry.get(field) or "").strip()
        if val:
            top = (entry.get("cas_top") or "").strip()
            return f"{val} TOP" if top and "TOP" not in val else val
    quartile = (entry.get("jcr_quartile") or entry.get("sjr_quartile") or "").strip()
    return quartile
