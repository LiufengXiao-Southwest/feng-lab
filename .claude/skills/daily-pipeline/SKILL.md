---
name: daily-pipeline
description: Diagnose and repair the FENG LAB daily literature pipeline — empty or wrong papers.json, missing or implausible impact factors, journals being silently dropped, Semantic Scholar 429s, failed GitHub Actions runs, stale journals.json, or broken full-text links. Use when the daily update produced no papers, produced papers with wrong metrics, or the workflow failed. Also use before changing anything in scripts/ so the ordering constraints are not broken.
---

# 每日流水线排错

这条流水线有顺序依赖和若干踩过的坑。改动前先读完本节。

## 流水线顺序（不可调换）

```
update_journal_metrics.py  →  data/journals.json
fetch_papers.py            →  papers.json / archive.json
enrich_fulltext.py         →  补 fulltext_* 字段
fetch_deep_read.py         →  deep_read*.json
build_site_data.py         →  feed.xml / feed.json / sitemap.xml
```

`fetch_papers.py` 依赖 `data/journals.json` 判定期刊是否过质量门槛。这一步失败或产出空文件，当天就会一篇都抓不到，且**不会报错**——只会安静地全部拒绝。查"今天没文献"先查这里。

## 症状 → 排查顺序

### 今天一篇文献都没有

1. `data/journals.json` 是否存在、`count` 是否合理（应 >40）？
   ```bash
   python -c "import json;d=json.load(open('data/journals.json',encoding='utf-8'));print(d['updated'],d['count'])"
   ```
   为空说明 `update_journal_metrics.py` 挂了 → 看该步日志。
2. Semantic Scholar 是否被限流？日志里找 `HTTP 429`。无 `SEMANTIC_SCHOLAR_API_KEY` 时是全体匿名用户共享速率池，白天极易触发。脚本有 5 次指数退避，仍失败会打印 `giving up`。
3. 质量门槛是否过严？跑一次单期刊判定看看：
   ```bash
   python -c "import sys;sys.path.insert(0,'scripts');import fetch_papers as F;print(F.lookup_journal('British Journal of Sports Medicine'))"
   ```

### 影响因子明显不对

**先怀疑期刊名匹配，不要怀疑数值本身。**

历史 bug：旧代码用 `if key in venue.lower()` 做子串匹配，`"sports medicine"` 同时命中了 `International Journal of Sports Medicine`（真实 2.3）、`Orthopaedic Journal of Sports Medicine`（2.9）、`Journal of Sports Medicine and Physical Fitness`（1.3），三者全部以 IF 9.8 发布。

验证匹配是否正确：
```bash
python -c "import sys;sys.path.insert(0,'scripts');from journal_metrics import JournalIndex,display_impact;i=JournalIndex.load();e=i.lookup('要查的刊名');print(e.get('name'),display_impact(e))"
```
返回的 `name` 和你查的刊名对不上，就是匹配问题，改 `scripts/journal_metrics.py` 的 `normalize_name` / `_ABBREV` / `_STOPWORDS`，并**先补一条测试到 `tests/test_journal_metrics.py`**。

数值本身存疑，跑交叉校验（对比 Scimago，比值超过 4 倍会报出来）：
```bash
python scripts/update_journal_metrics.py --check
```

### IF 显示为空 / 显示的不是 IF

`impact_factor` 永远配一个 `if_source`。级联只有第一级是真正的影响因子：

| `if_source` | 含义 |
|---|---|
| `JCR 2024` | 真实影响因子（easyScholar 或人工种子表） |
| `SJR 2年篇均被引` | Scimago 指标，**不是 IF** |
| `OpenAlex 2年均被引` | 最后兜底，**不是 IF**，且对含大量会议摘要的刊严重偏低 |
| 空 | 该刊无任何指标，前端不显示徽章 |

⚠️ 不要为了"让徽章都有值"而把 OpenAlex 的数当 IF 显示。MSSE 在该指标下只有 0.46（真实 IF 4.0）。

### 某个该收录的期刊被丢了

门槛在 `fetch_papers.py:_passes_gate`。满足任一条即通过：IF ≥ 3.0 / JCR 或 SJR 分区 Q1 / 中科院 1 区或 2 区 / 在 `always_include` 名单里。

缓存里没有的期刊会**实时解析**（`resolve_live`），不再直接丢弃。若实时解析也失败，日志会打印 `live lookup failed`。

想强制收录某刊（编辑偏好，与指标无关），加到 `data/jcr_seed.json` 的 `always_include` 数组。

### 全文链接失效

`enrich_fulltext.py` 的级联：Europe PMC → Unpaywall → OpenAlex → S2 → DOI 落地页。

- Unpaywall 静默跳过 → `CONTACT_EMAIL` 没配或配了占位邮箱（占位值返回 HTTP 422）。
- 重新解析全部：`python scripts/enrich_fulltext.py --all --force`
- **不要往这个脚本里加 Sci-Hub / LibGen / 代理源**，这是公开发布的站点。

## 改代码前必做

```bash
python -m unittest tests.test_fetch_papers tests.test_journal_metrics
```

前端改动不要只看代码，用 `webapp-testing` skill 起本地服务实际打开验证。

## 密钥

全部走环境变量，仓库公开，绝不硬编码。缺失时对应功能降级而非中断：
`EASYSCHOLAR_SECRET_KEY`（IF+分区）、`SEMANTIC_SCHOLAR_API_KEY`（限速）、`CONTACT_EMAIL`（Unpaywall 必填真实邮箱）、`OPENALEX_API_KEY`（额度）、`GEMINI_API_KEY`（翻译）、`FEISHU_WEBHOOK`（通知）。
