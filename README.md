# FENG LAB 每日科研简报

自动抓取运动科学相关论文，每天选出全站前 6 篇展示在首页，并把历史结果按日期保存到归档页。

## 技术架构

- 静态页面：`index.html`、`archive.html`、`deep-read.html`、`style.css`、`app.js`
- 数据文件：`data/papers.json` 保存当天 6 篇，`data/archive.json` 保存历史日期索引
- 自动任务：GitHub Actions 每天 09:00（北京时间）运行完整流水线
- 精读流程：`scripts/fetch_deep_read.py` 和 `data/deep_read*.json`，与普通文献列表独立
- 订阅：`feed.xml`（Atom）、`feed.json`（JSON Feed）

详细的模块职责和调用关系见 [ARCHITECTURE.md](ARCHITECTURE.md)，开发约定见 [CLAUDE.md](CLAUDE.md)。

## 期刊指标怎么来的

影响因子按优先级级联获取，**每个数值都带来源标注**，前端会把来源显示出来：

| 来源 | 提供 | 更新频率 |
|---|---|---|
| easyScholar API | JCR 影响因子、JCR 分区、中科院大类/小类分区 | 每次运行 |
| `data/jcr_seed.json` | 人工维护的 JCR 兜底值 | 每年一次 |
| `data/scimago_*.csv` | SJR、Scopus 分区、2 年篇均被引 | 每年一次（手工） |
| OpenAlex | 刊名、ISSN、别名、h-index、OA 状态 | 每次运行 |

⚠️ OpenAlex 的 `2yr_mean_citedness` **不是影响因子**，它把会议摘要算进分母（MSSE 因此只有 0.46，真实 IF 是 4.0），只作最后兜底且会明确标注。真正的 JCR 影响因子是 Clarivate 的专有数据，每年 6 月发布一次，没有可以合法自动抓取的渠道——所谓"实时更新"的实质是**保证数值正确、覆盖完整、且不会随时间腐坏**。

### 年度维护（每年 6 月 JCR 发布后）

```bash
# 1. 刷新 Scimago 快照（必须在本机跑，CI 出口 IP 会被 Cloudflare 拦）
curl -sSL -o data/scimago_3612.csv -H "User-Agent: Mozilla/5.0" \
  -H "Referer: https://www.scimagojr.com/journalrank.php" \
  "https://www.scimagojr.com/journalrank.php?category=3612&out=xls"
```

```bash
# 2. 交叉校验所有数值，报告与 Scimago 差异过大的条目
python scripts/update_journal_metrics.py --check
```

```bash
# 3. 重新生成缓存并回填历史数据
python scripts/update_journal_metrics.py && python scripts/backfill_metrics.py
```

## 环境变量

本地运行需要，CI 里配成 GitHub Secrets。全部可选，缺失时对应功能降级而不会中断流水线。

| 名称 | 用途 |
|---|---|
| `EASYSCHOLAR_SECRET_KEY` | JCR 影响因子 + 中科院分区 |
| `SEMANTIC_SCHOLAR_API_KEY` | 抓取限速，免费申请，显著降低 429 风险 |
| `CONTACT_EMAIL` | Unpaywall 必填参数，**必须是真实邮箱**（占位值会被 422 拒绝） |
| `OPENALEX_API_KEY` | OpenAlex 额度，免费申请 |
| `GEMINI_API_KEY` | 中文翻译与精读生成 |
| `FEISHU_WEBHOOK` | 飞书推送 |

## 本地运行

页面可直接打开 `index.html`，或用任意静态服务器：

```bash
python -m http.server 8000
```

⚠️ **不要在本地运行 `scripts/fetch_papers.py`**。Semantic Scholar 无 key 时是全体匿名用户共享速率池，本地跑极易 429，并会污染当天的 `papers.json`。验证逻辑请跑测试。

## 测试

```bash
python -m unittest tests.test_fetch_papers tests.test_journal_metrics
```

## 部署

仓库包含 `vercel.json`，可部署到 Vercel。GitHub Actions 会自动提交每日数据更新。

## 数据来源致谢

- SCImago, (n.d.). SJR — SCImago Journal & Country Rank [Portal]. Powered by Scopus.
- OpenAlex（CC0）、Semantic Scholar、Unpaywall、Europe PMC、easyScholar
