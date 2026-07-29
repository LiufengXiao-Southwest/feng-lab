#!/usr/bin/env python3
"""
FENG LAB — Build syndication feeds and sitemap from the archive.

A daily literature digest is subscription-shaped content, but the site had no
feed, so the only way to follow it was to remember to visit. This emits:

* ``feed.xml``   — Atom 1.0, for FreshRSS / Inoreader / Feishu bots
* ``feed.json``  — JSON Feed 1.1
* ``sitemap.xml``— one entry per archived day, so search engines can index them

All three are generated from ``data/archive.json`` and committed by the daily
workflow. No build step, no dependencies beyond the standard library.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
ARCHIVE = DATA / "archive.json"

SITE_URL = "https://feng-lab.vercel.app"
SITE_TITLE = "FENG LAB 每日科研简报"
SITE_SUBTITLE = "运动科学 · 生物力学 · 运动表现 · 运动补剂"
FEED_DAYS = 30      # days of history to syndicate
AUTHOR = "FENG LAB"


def load_days() -> list[tuple[str, list[dict]]]:
    if not ARCHIVE.exists():
        return []
    archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    days = sorted(archive.get("dates", {}).items(), reverse=True)
    return [(d, papers) for d, papers in days if papers]


def paper_line(p: dict) -> str:
    """One paper rendered as an HTML list item for the feed body."""
    title = escape(p.get("title_zh") or p.get("title_en") or "")
    title_en = escape(p.get("title_en") or "")
    journal = escape(p.get("journal") or "")
    year = escape(str(p.get("year") or ""))
    doi = (p.get("doi") or "").strip()
    link = p.get("fulltext_url") or (f"https://doi.org/{doi}" if doi else "")

    badges = []
    if p.get("impact_factor"):
        src = escape(p.get("if_source") or "")
        badges.append(f"IF {escape(str(p['impact_factor']))}" + (f" ({src})" if src else ""))
    if p.get("journal_tier"):
        badges.append(escape(p["journal_tier"]))
    if p.get("is_open_access"):
        badges.append("Open Access")
    badge_html = f" <em>[{' · '.join(badges)}]</em>" if badges else ""

    tldr = escape(p.get("tldr_zh") or p.get("tldr_en") or "")
    abstract = escape((p.get("abstract_zh") or p.get("abstract_en") or "")[:400])

    heading = f'<a href="{escape(link)}">{title}</a>' if link else title
    parts = [f"<li><p><strong>{heading}</strong>{badge_html}<br/>"]
    if title_en and title_en != title:
        parts.append(f"<span>{title_en}</span><br/>")
    parts.append(f"<small>{journal} · {year}</small></p>")
    if tldr:
        parts.append(f"<p><strong>一句话结论：</strong>{tldr}</p>")
    if abstract:
        parts.append(f"<p>{abstract}…</p>")
    parts.append("</li>")
    return "".join(parts)


def day_html(date: str, papers: list[dict]) -> str:
    items = "".join(paper_line(p) for p in papers)
    return f"<p>{date} 共 {len(papers)} 篇。</p><ul>{items}</ul>"


def build_atom(days: list[tuple[str, list[dict]]]) -> str:
    updated = f"{days[0][0]}T01:30:00Z" if days else \
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = []
    for date, papers in days[:FEED_DAYS]:
        url = f"{SITE_URL}/archive.html#date={date}"
        entries.append(f"""  <entry>
    <title>{escape(SITE_TITLE)} · {date}</title>
    <link href="{escape(url)}"/>
    <id>tag:feng-lab,{date}:digest</id>
    <updated>{date}T01:30:00Z</updated>
    <author><name>{escape(AUTHOR)}</name></author>
    <content type="html">{escape(day_html(date, papers))}</content>
  </entry>""")

    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{escape(SITE_TITLE)}</title>
  <subtitle>{escape(SITE_SUBTITLE)}</subtitle>
  <link href="{SITE_URL}/"/>
  <link rel="self" href="{SITE_URL}/feed.xml"/>
  <id>{SITE_URL}/</id>
  <updated>{updated}</updated>
  <author><name>{escape(AUTHOR)}</name></author>
{chr(10).join(entries)}
</feed>
"""


def build_json_feed(days: list[tuple[str, list[dict]]]) -> str:
    items = []
    for date, papers in days[:FEED_DAYS]:
        items.append({
            "id": f"{SITE_URL}/archive.html#date={date}",
            "url": f"{SITE_URL}/archive.html#date={date}",
            "title": f"{SITE_TITLE} · {date}",
            "content_html": day_html(date, papers),
            "date_published": f"{date}T01:30:00Z",
            "tags": sorted({p.get("category", "") for p in papers} - {""}),
        })
    return json.dumps({
        "version": "https://jsonfeed.org/version/1.1",
        "title": SITE_TITLE,
        "description": SITE_SUBTITLE,
        "home_page_url": f"{SITE_URL}/",
        "feed_url": f"{SITE_URL}/feed.json",
        "language": "zh-CN",
        "authors": [{"name": AUTHOR}],
        "items": items,
    }, ensure_ascii=False, indent=2)


def build_sitemap(days: list[tuple[str, list[dict]]]) -> str:
    urls = [
        f"  <url><loc>{SITE_URL}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{SITE_URL}/archive.html</loc><changefreq>daily</changefreq><priority>0.8</priority></url>",
        f"  <url><loc>{SITE_URL}/deep-read.html</loc><changefreq>daily</changefreq><priority>0.8</priority></url>",
        f"  <url><loc>{SITE_URL}/deep-read-archive.html</loc><changefreq>daily</changefreq><priority>0.6</priority></url>",
    ]
    for date, _ in days:
        urls.append(
            f"  <url><loc>{SITE_URL}/archive.html#date={date}</loc>"
            f"<lastmod>{date}</lastmod><priority>0.5</priority></url>"
        )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls) + "\n</urlset>\n")


def main() -> int:
    days = load_days()
    if not days:
        print("[!] No archive data — nothing to build.")
        return 0

    (ROOT / "feed.xml").write_text(build_atom(days), encoding="utf-8")
    (ROOT / "feed.json").write_text(build_json_feed(days), encoding="utf-8")
    (ROOT / "sitemap.xml").write_text(build_sitemap(days), encoding="utf-8")
    (ROOT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")

    total = sum(len(p) for _, p in days)
    print(f"✓ feed.xml / feed.json  — {min(len(days), FEED_DAYS)} days")
    print(f"✓ sitemap.xml           — {len(days) + 4} URLs")
    print(f"✓ robots.txt")
    print(f"  ({len(days)} archived days, {total} papers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
