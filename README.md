# 珠峰工作台

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

- 增删 RSS 源、行情标的、城市：编辑 `config/sources.json`（**只放通用内容**）
- **个人化配置（关注城市等）**：写进 `config/sources.local.json`。该文件已在 `.gitignore` 中，
  不会随仓库外泄；它会深度覆盖 `sources.json` 的同名设置。详情见下面「个人信息怎么放」。
- 写知识库笔记：`knowledge/notes/` 放**公开笔记**（入库，会渲染到线上页面）
- 采集频率：`.github/workflows/fetch.yml` 中的 cron 表达式

## 个人信息怎么放

公开站点的仓库必须是 public（Pages 免费版只能服务公开仓库），个人信息又不能进公开仓库，
所以这两类东西**物理分开**：

```
Zfeng08/work-buddy          公开 —— 页面 / 脚本 / 公开数据（这个仓库）
Zfeng08/work-buddy-private  私有 —— 私人笔记 / 个人配置 / 完整索引
```

公开仓库里与个人相关的路径**全部被 .gitignore 排除**，只在本机存在：

| 本地路径 | 内容 | 来源 |
|---|---|---|
| `knowledge/_private/` | 私有笔记 | `scripts/sync_private.py` 从私有库拉取 |
| `config/sources.local.json` | 个人关注的天气/岗位城市 | 同上 |
| `data/knowledge.local.json` | 含私有笔记的完整索引 | `build_knowledge.py` 本地生成 |
| `config/private.key` | 加密口令 | `build_private_bundle.py --gen` 生成 |

**线上也能看私有笔记**：私有笔记在本地加密后产出 `data/private.enc.json`（PBKDF2-HMAC-SHA256
60 万次 + AES-256-GCM），这个**密文文件才会提交进公开仓库**。页面上输入口令后由浏览器
WebCrypto 就地解密，明文从不落到服务器或仓库里。注意密文是公开可下载的，**口令强度即全部安全性**。

```bash
# 本机：从私有库拉取个人内容
python scripts/sync_private.py            # 需要先把私有库 clone 到本地
python scripts/build_knowledge.py         # 重建索引（含私有笔记）
python scripts/build_private_bundle.py    # 加密产出 data/private.enc.json
```

## 启用 Pages

仓库 Settings → Pages → Source 选择 **GitHub Actions**。

## 本地运行

```bash
pip install requests feedparser beautifulsoup4 jieba cryptography
python scripts/fetch_news.py       # 任意采集脚本
python scripts/sync_private.py     # 拉取私有库的个人内容（可选）
python scripts/build_knowledge.py  # 知识库分析
python -m http.server 8000         # 本地预览 http://localhost:8000
```
