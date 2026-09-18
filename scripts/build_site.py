"""把要发布的静态站点拼装到 dist/（供 Cloudflare Pages 部署）。

只收录页面真正需要的文件 —— 绝不把 .git / scripts / .github / knowledge 等
内部内容推到 CDN 上。`data/*.local.json`（本地私有快照）也会被排除。
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# 站点直接需要的页面级文件与目录
FILES = ["index.html", "manifest.json"]
DIRS = ["assets"]


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    for f in FILES:
        src = ROOT / f
        if src.exists():
            shutil.copy2(src, DIST / f)

    for d in DIRS:
        src = ROOT / d
        if src.exists():
            shutil.copytree(src, DIST / d)

    data_out = DIST / "data"
    data_out.mkdir(exist_ok=True)
    n = 0
    for p in sorted((ROOT / "data").glob("*.json")):
        if p.name.endswith(".local.json"):   # 本地私有快照，不上线
            continue
        shutil.copy2(p, data_out / p.name)
        n += 1

    print(f"[ok] dist/ 已生成：{len(FILES)} 个页面文件 + assets/ + {n} 个数据文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
