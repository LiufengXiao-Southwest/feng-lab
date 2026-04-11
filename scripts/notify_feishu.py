#!/usr/bin/env python3
"""
FENG LAB — Feishu Daily Notification
Sends today's deep read + new papers to a Feishu/Lark webhook.

Requires: FEISHU_WEBHOOK environment variable (webhook URL from Feishu group bot)
"""
import json
import os
import sys
import datetime
import requests
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

TODAY = datetime.date.today().isoformat()
ROOT  = Path(__file__).parent.parent

CAT_ZH = {
    'biomechanics': '生物力学',
    'performance':  '运动表现',
    'supplements':  '运动补剂',
    'preprint':     '预印本',
}

SITE_URL      = "https://liufengxiao-southwest.github.io/feng-lab/"
DEEP_READ_URL = SITE_URL + "deep-read.html"
ARCHIVE_URL   = SITE_URL + "archive.html"


def load_json(path):
    if Path(path).exists():
        return json.loads(Path(path).read_text(encoding='utf-8'))
    return {}


def build_card(papers_data: dict, deep_read: dict) -> dict:
    today_papers = [
        p for p in papers_data.get('papers', [])
        if p.get('date_added') == TODAY
    ]

    # ── Deep Read block ──
    dr_title   = deep_read.get('title_zh') or deep_read.get('title_en', '暂无精读')
    dr_journal = deep_read.get('journal', '')
    dr_if      = deep_read.get('impact_factor', '')
    dr_cite    = deep_read.get('citation_count', '')
    dr_meta    = ' · '.join(filter(None, [
        dr_journal,
        f'IF {dr_if}' if dr_if else '',
        f'{dr_cite} 引用' if dr_cite else '',
    ]))

    # ── Paper list block ──
    lines = []
    for p in today_papers[:6]:
        title = p.get('title_zh') or p.get('title_en', '')
        cat   = CAT_ZH.get(p.get('category', ''), '')
        journal = p.get('journal', '')
        cit   = p.get('citation_count', '')
        meta  = ' · '.join(filter(None, [journal, f'{cit} 引用' if cit else '']))
        lines.append(
            f"**[{cat}]** {title[:55]}{'…' if len(title) > 55 else ''}"
            + (f"\n_{meta}_" if meta else '')
        )

    paper_block = (
        f"**今日新增 {len(today_papers)} 篇**\n\n" + "\n\n".join(lines)
        if lines else "今日暂无新增文献"
    )

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"FENG LAB 科研简报  {TODAY}"
                },
                "template": "orange"
            },
            "elements": [
                # Deep read section
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**◎ 今日精读**\n"
                            f"{dr_title}"
                            + (f"\n_{dr_meta}_" if dr_meta else "")
                        )
                    }
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "进入精读 →"},
                            "url": DEEP_READ_URL,
                            "type": "primary"
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "全部文献"},
                            "url": SITE_URL,
                            "type": "default"
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "文献归档"},
                            "url": ARCHIVE_URL,
                            "type": "default"
                        }
                    ]
                },
                {"tag": "hr"},
                # Papers section
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": paper_block
                    }
                }
            ]
        }
    }


def main():
    webhook = os.environ.get('FEISHU_WEBHOOK', '')
    if not webhook:
        print('[!] FEISHU_WEBHOOK not set, skipping notification.')
        return

    papers_data = load_json(ROOT / 'data' / 'papers.json')
    deep_read   = load_json(ROOT / 'data' / 'deep_read.json')

    card = build_card(papers_data, deep_read)

    try:
        r = requests.post(webhook, json=card, timeout=15)
        r.raise_for_status()
        result = r.json()
        if result.get('code') == 0 or result.get('StatusCode') == 0:
            print(f'✓ Feishu notification sent successfully.')
        else:
            print(f'[!] Feishu returned: {result}')
    except Exception as e:
        print(f'[!] Feishu send failed: {e}')


if __name__ == '__main__':
    main()
