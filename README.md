# FENG LAB 每日科研简报

自动抓取运动科学相关论文，每天选出全站前 6 篇展示在首页，并把历史结果按日期保存到归档页。

## 技术架构

- 静态页面：`index.html`、`archive.html`、`style.css`、`app.js`
- 数据文件：`data/papers.json` 保存当天 6 篇，`data/archive.json` 保存历史日期索引
- 自动任务：GitHub Actions 每天运行 `scripts/fetch_papers.py`
- 精读流程：独立使用 `scripts/fetch_deep_read.py` 和 `data/deep_read*.json`

## 本地运行

可直接打开 `index.html`，或用任意静态服务器打开项目目录。

## 部署

仓库包含 `vercel.json`，可部署到 Vercel。GitHub Actions 会自动提交每日数据更新。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_fetch_papers
.\.venv\Scripts\python.exe -m py_compile scripts\fetch_papers.py
```

不要在本地运行 `scripts/fetch_papers.py`，避免 Semantic Scholar 429 和密钥暴露。

## 搜索记录

本次为既有项目改版，未新增外部方案搜索。

## 已完成功能

- 首页只显示当天论文，空状态显示“今日暂无新文献”
- 每日抓取在全部分类中按引用数、影响因子、年份取前 6
- 归档页按日期侧栏、日期输入框、前后一天按钮和 `#date=YYYY-MM-DD` 路由查看
- 历史数据已从旧 `papers.json` 迁移到 `archive.json`

## 待办事项

- 暂无
