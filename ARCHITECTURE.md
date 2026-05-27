# 架构说明

## 文件职责

- `index.html`：首页结构，展示每日论文卡片和精读入口。
- `app.js`：首页数据加载、筛选、收藏、引用导出和卡片渲染。
- `archive.html`：归档页，按日期读取并展示历史论文。
- `style.css`：全站视觉样式。
- `scripts/fetch_papers.py`：抓取 Semantic Scholar，筛选当天前 6 篇，写入当天数据和历史归档。
- `scripts/fetch_deep_read.py`：每日精读生成流程，和普通文献列表独立。
- `scripts/notify_feishu.py`：飞书通知。
- `data/papers.json`：当天首页数据，每天覆盖。
- `data/archive.json`：历史文献数据，按日期保存。
- `.github/workflows/daily-update.yml`：每日自动抓取、精读、提交和通知。

## 调用关系

- GitHub Actions 调用 `scripts/fetch_papers.py`，写入 `data/papers.json` 和 `data/archive.json`。
- 首页 `app.js` 读取 `data/papers.json`。
- 归档页 `archive.html` 读取 `data/archive.json`。
- 精读页面继续读取 `data/deep_read*.json`，不依赖普通文献归档。

## 关键决定

- 当天文献不再累积到 `papers.json`，避免首页越来越长。
- 历史数据集中进入 `archive.json`，归档页只按日期读取。
- 每日 6 篇从全部分类统一排序，不再设置分类上限。
