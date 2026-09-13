# WorkBuddy 工作台

个人数据中心：GitHub 仓库即数据源，Actions 定时采集，Pages 展示。

## 结构

```
├── index.html          # 展示页面（GitHub Pages 托管）
├── assets/             # 样式与前端逻辑
├── data/               # 定时任务产出的数据（JSON）
├── knowledge/          # 个人知识库（Markdown 笔记）
│   └── notes/          #   在这里写 .md 笔记
├── scripts/            # 采集与分析脚本（Python）
├── config/sources.json # 数据源配置（RSS/行情/城市/岗位关键词）
└── .github/workflows/  # fetch.yml 定时采集 + deploy.yml 页面部署
```

## 数据流

```
GitHub Actions (cron, 每天北京时间 9/13/17 点)
  → scripts/fetch_*.py 采集 资讯/行情/天气/趋势/岗位
  → scripts/build_knowledge.py 分析知识库笔记与关联
  → git commit 回本仓库
  → deploy.yml 自动更新 Pages 页面
```

## 定制

- 增删 RSS 源、行情标的、关注城市：编辑 `config/sources.json`
- 岗位关键词过滤（默认：远程/昆明/云南/remote）：`config/sources.json` 的 `jobs.highlight_keywords`
- 写知识库笔记：在 `knowledge/notes/` 新建 Markdown，带 front-matter，支持 `[[标题]]` 双向链接
- 采集频率：`.github/workflows/fetch.yml` 中的 cron 表达式

## 启用 Pages

仓库 Settings → Pages → Source 选择 **GitHub Actions**。

## 本地运行

```bash
pip install requests feedparser
python scripts/fetch_news.py       # 任意采集脚本
python scripts/build_knowledge.py  # 知识库分析
python -m http.server 8000         # 本地预览 http://localhost:8000
```
