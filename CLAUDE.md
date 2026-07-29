# FENG LAB — 项目规则

运动科学每日文献简报。纯静态站 + GitHub Actions 每日抓取，部署在 Vercel。

## 绝对不要做的事

- **不要在本地运行 `scripts/fetch_papers.py`**。Semantic Scholar 无 key 时是全体匿名用户共享一个池子，本地跑极易触发 429，并污染当天的 `papers.json`。要验证逻辑请跑测试。
- **不要把任何密钥写进代码或 JSON**。仓库是公开的。所有密钥走 GitHub Secrets + `os.environ`。
- **不要把 Sci-Hub / LibGen / 任何代理下载路径写进这个仓库**。这是公开发布的网站。个人本地用 scansci-pdf 取全文是另一回事，两者不能混。
- **不要手工编辑 `data/journals.json`**。它是 `scripts/update_journal_metrics.py` 的产物，手改会在下次运行时被覆盖。要改数值请改 `data/jcr_seed.json`。

## 影响因子从哪来

按优先级级联，每一级都在数据里标了来源（`if_source` 字段），前端必须把来源显示出来：

1. **easyScholar API**（主）— 真实 JCR IF、JCR 分区、中科院大类/小类分区。密钥走 `EASYSCHOLAR_SECRET_KEY`。
2. **`data/jcr_seed.json`**（兜底）— 人工维护，仅在 easyScholar 查不到时使用。
3. **`data/scimago_*.csv`**（补充）— SJR、Scopus 分区、2年篇均被引。每年手工刷新一次快照，**不要放进 CI 拉取**：scimagojr.com 在 Cloudflare 后面，会封 CI 出口 IP。
4. **OpenAlex**（元数据）— 刊名、ISSN、别名、h-index、OA 状态。

⚠️ **OpenAlex 的 `2yr_mean_citedness` 不是影响因子，不要当 IF 显示**。它把会议摘要算进分母——MSSE 索引了约 4.8 万条摘要，该指标只有 0.46，而真实 IF 是 4.0。与 JCR 的等级相关仅 0.607（Scimago 是 0.964）。它只作为最后兜底，且必须标注为 "OpenAlex 2年均被引"。

## 期刊名匹配

`scripts/journal_metrics.py` 里的 `JournalIndex`。匹配顺序：**ISSN → 规范化全名精确匹配 → 最长子串匹配**。

历史教训：旧代码用朴素子串匹配（`if key in venue`），`"sports medicine"` 这个 key 命中了 `International Journal of Sports Medicine`、`Orthopaedic Journal of Sports Medicine`、`Journal of Sports Medicine and Physical Fitness`，让它们全部以 IF 9.8 发布（真实值分别是 2.3 / 2.9 / 1.3），190 篇归档里有 39 篇带着这个错误数字。改动这块逻辑前先跑 `tests/test_journal_metrics.py`，那里的用例就是照着这个 bug 写的。

## 每日流水线顺序

`.github/workflows/daily-update.yml` 里的顺序有依赖，不要随意调换：

```
update_journal_metrics.py   → data/journals.json   （必须最先，后面都读它）
fetch_papers.py             → papers.json + archive.json
enrich_fulltext.py          → 补全文链接
fetch_deep_read.py          → deep_read*.json
build_site_data.py          → feed.xml / feed.json / sitemap.xml
```

## 环境变量 / GitHub Secrets

| 名称 | 用途 | 缺失时的行为 |
|---|---|---|
| `EASYSCHOLAR_SECRET_KEY` | JCR IF + 中科院分区 | 退回 `jcr_seed.json` + Scimago |
| `SEMANTIC_SCHOLAR_API_KEY` | 抓取限速 | 仍可用，但 429 风险高、退避更慢 |
| `CONTACT_EMAIL` | Unpaywall 必填参数 | 跳过 Unpaywall（占位邮箱会被 422 拒绝） |
| `OPENALEX_API_KEY` | OpenAlex 额度 | 匿名 $0.1/天，CI 共享 IP 可能耗尽 |
| `GEMINI_API_KEY` | 中文翻译 + 精读生成 | 跳过翻译 |
| `FEISHU_WEBHOOK` | 飞书推送 | 跳过通知 |

## 测试

```bash
python -m unittest tests.test_fetch_papers tests.test_journal_metrics
```

改抓取或指标逻辑必须先让这两个模块通过。前端改动用 `.claude/skills/webapp-testing` 起本地服务实际验证，不要只看代码。

## 数据字段约定

前端渲染必须对新字段**容错**（有就显示、没有就不显示），因为归档里的老数据不会有全部字段：

- `impact_factor` / `if_source` — 数值与来源标注，成对出现
- `journal_tier` — 中科院分区或 JCR 分区
- `evidence` — `meta` / `review` / `trial` / 空
- `tldr_en` / `tldr_zh` — 一句话结论
- `fulltext_url` / `fulltext_type` / `fulltext_label` — 全文获取路径与等级
