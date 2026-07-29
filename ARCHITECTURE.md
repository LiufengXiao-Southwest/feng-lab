# 架构说明

## 文件职责

### 页面
- `index.html`：首页结构，展示每日论文卡片和精读入口。
- `app.js`：首页数据加载、筛选、搜索、收藏、引用导出和卡片渲染。
- `archive.html`：归档页，按日期读取并展示历史论文。
- `deep-read.html` / `deep-read-archive.html`：每日精读与其存档。
- `style.css`：全站视觉样式。

### 抓取与数据脚本
- `scripts/journal_metrics.py`：**期刊指标查询模块**。被所有其他脚本引用。负责把 venue 字符串解析到期刊条目（ISSN → 规范化全名 → 最长子串），并决定卡片上显示哪个数值、标注什么来源。
- `scripts/update_journal_metrics.py`：生成 `data/journals.json`。easyScholar（JCR IF + 中科院分区）+ Scimago 快照（SJR/分区）+ OpenAlex（刊名/ISSN/h-index）。
- `scripts/fetch_papers.py`：抓取 Semantic Scholar，按期刊质量门槛过滤，选出当天前 6 篇。
- `scripts/enrich_fulltext.py`：为每篇论文解析合法的开放全文路径（Europe PMC → Unpaywall → OpenAlex → S2 → DOI）。
- `scripts/fetch_deep_read.py`：每日精读生成，和普通文献列表独立。
- `scripts/build_site_data.py`：生成 `feed.xml`、`feed.json`、`sitemap.xml`、`robots.txt`。
- `scripts/backfill_metrics.py`：把修正后的期刊指标回写到已发布的历史数据（一次性/按需）。
- `scripts/notify_feishu.py`：飞书通知。

### 数据文件
- `data/journals.json`：**生成物**，期刊指标缓存。不要手工编辑。
- `data/jcr_seed.json`：人工维护的 JCR 兜底表，仅在 easyScholar 查不到时生效。
- `data/scimago_*.csv`：Scimago 快照，每年手工刷新（CI 拉不到，见下）。
- `data/papers.json`：当天首页数据，每天覆盖。
- `data/archive.json`：历史文献数据，按日期保存。
- `data/deep_read*.json`：精读数据。

## 调用关系

```
update_journal_metrics.py ──> data/journals.json
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            fetch_papers.py  fetch_deep_read.py  backfill_metrics.py
                    │
                    ▼
            papers.json / archive.json
                    │
                    ▼
            enrich_fulltext.py  ──> 补 fulltext_* 字段
                    │
                    ▼
            build_site_data.py  ──> feed.xml / feed.json / sitemap.xml
```

前端：首页 `app.js` 读 `data/papers.json`；归档页读 `data/archive.json`；精读页读 `data/deep_read*.json`。

## 关键决定

### 期刊指标
- **指标来源分层，并在 UI 标注**。`impact_factor` 永远配一个 `if_source`，因为级联里只有第一级（easyScholar/JCR）才是真正的影响因子，Scimago 和 OpenAlex 的数是别的东西，不能冒充。
- **OpenAlex 的 `2yr_mean_citedness` 不作为 IF**。它把会议摘要计入分母，MSSE 因此只有 0.46（真实 IF 4.0），与 JCR 的等级相关仅 0.607。仅作最后兜底。
- **Scimago 走仓库内快照，不在 CI 拉取**。scimagojr.com 在 Cloudflare 后面，会封 CI 出口 IP；且 SJR 一年只更新一次，定时抓取本身没有意义。
- **期刊匹配以 ISSN 优先**。旧实现用朴素子串匹配，`"sports medicine"` 命中了三个不相干的期刊，让它们全部以 IF 9.8 发布，190 篇归档里污染了 39 篇。

### 内容筛选
- **未收录的期刊不再直接丢弃**。旧逻辑把"不在硬编码字典里"等同于"非 Q1"，导致 Nature、Lancet、J Physiol 这类期刊的论文永远进不来。现在按指标阈值动态判定。
- **排序用引用速率而非引用总数**。按总引用数排序会结构性偏向窗口内最老的论文，让"每日简报"总在推三年前的旧文。现在用 `引用数/年龄` + 新近度加成 + 证据等级加成。
- **预印本类目做真实性校验**。旧代码对 preprint 类目跳过全部过滤，实际上让一批普通期刊论文从这个口子漏进来。现在按 DOI 前缀（10.1101/ 等）和期刊标记判定。

### 全文获取
- **只用合法开放源**。Europe PMC 是唯一能拿到结构化全文（JATS XML）的免费端点，优先级最高。仓库里不包含任何 Sci-Hub / LibGen / 代理路径——这是公开发布的站点。
- **`fulltext_type` 分级展示**。读者需要在点击前就知道这篇是能直接读全文、还是只有摘要。

### 数据结构
- 当天文献不再累积到 `papers.json`，避免首页越来越长。
- 历史数据集中进入 `archive.json`，归档页只按日期读取。
- 每日 6 篇从全部分类统一排序，不再设置分类上限。
- 前端对所有新增字段容错渲染，因为历史归档不会有完整字段。
