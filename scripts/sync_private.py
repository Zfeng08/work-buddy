"""把私有库 Zfeng08/work-buddy-private 的个人内容同步到本地工作副本。

为什么要这个脚本
----------------
公开站点的仓库必须是 public（GitHub Pages 免费版只能服务公开仓库），
而个人信息不能进公开仓库。所以拆成两个库：

    Zfeng08/work-buddy          公开 —— 页面 / 脚本 / 公开数据
    Zfeng08/work-buddy-private  私有 —— 私人笔记 / 个人配置 / 完整索引

本脚本负责把私有库的内容拉到本地工作副本里，写入的位置全部被 .gitignore 排除，
**永远不会被提交到公开库**，因此线上站点看不到它们，只有本机预览能看到。

同步内容
--------
    <private>/knowledge/private/*.md   ->  knowledge/_private/*.md
    <private>/config/sources.local.json ->  config/sources.local.json

用法
----
    python scripts/sync_private.py             # 拉取（私有库 -> 本地）
    python scripts/sync_private.py --check     # 只报告差异，不写文件
    python scripts/sync_private.py --push      # 反向：把本地改动推回私有库
    python scripts/sync_private.py --dir D:\\path   # 指定私有库工作副本位置

私有库工作副本默认在 C:\\openclaw\\project\\work-buddy-private，
也可以用环境变量 WORKBUDDY_PRIVATE_DIR 指定。
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PRIVATE_DIR = Path(r"C:\openclaw\project\work-buddy-private")

# 同步映射：(私有库内的相对路径, 本地工作副本内的相对路径)
FILE_MAP = [
    ("config/sources.local.json", "config/sources.local.json"),
]
# 目录镜像：源目录里的 *.md 会整体覆盖到目标目录
DIR_MAP = [
    ("knowledge/private", "knowledge/_private"),
]


def private_dir(override: str | None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("WORKBUDDY_PRIVATE_DIR")
    return Path(env) if env else DEFAULT_PRIVATE_DIR


def git(repo: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or p.stderr or "").strip()


def pdir(repo: Path, *parts: str) -> Path:
    """在私有库内拼路径，相对路径统一用 / 分隔，跨平台安全。"""
    return repo.joinpath(*[p for part in parts for p in part.split("/")])


def pull(repo: Path, check_only: bool) -> int:
    rc, out = git(repo, "pull", "--ff-only")
    print(f"[git pull] {'ok' if rc == 0 else '跳过'} {out.splitlines()[0] if out else ''}")

    changes: list[str] = []

    for src_rel, dst_rel in FILE_MAP:
        src, dst = pdir(repo, src_rel), ROOT.joinpath(*dst_rel.split("/"))
        if not src.exists():
            print(f"  ! 私有库里没有 {src_rel}，跳过")
            continue
        same = dst.exists() and filecmp.cmp(src, dst, shallow=False)
        print(f"  {'=' if same else '→'} {dst_rel}  {'无变化' if same else '待更新'}")
        if not same:
            changes.append(dst_rel)
            if not check_only:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    for src_rel, dst_rel in DIR_MAP:
        src_dir, dst_dir = pdir(repo, src_rel), ROOT.joinpath(*dst_rel.split("/"))
        if not src_dir.is_dir():
            print(f"  ! 私有库里没有 {src_rel}/，跳过")
            continue
        want = {p.name: p for p in src_dir.glob("*.md")}
        have = {p.name: p for p in dst_dir.glob("*.md")} if dst_dir.is_dir() else {}
        renamed = sorted(set(want) | set(have))
        before = len(changes)
        for name in renamed:
            if name not in have:
                print(f"  + {dst_rel}/{name}  新增")
            elif name not in want:
                print(f"  - {dst_rel}/{name}  私有库已删除")
            elif not filecmp.cmp(want[name], have[name], shallow=False):
                print(f"  → {dst_rel}/{name}  内容不同")
            else:
                continue
            changes.append(f"{dst_rel}/{name}")
            if not check_only:
                dst_dir.mkdir(parents=True, exist_ok=True)
                if name in want:
                    shutil.copy2(want[name], dst_dir / name)
                else:
                    (dst_dir / name).unlink()

        if len(changes) == before:
            print(f"  = {dst_rel}/  {len(want)} 篇，无变化")

    print()
    if not changes:
        print("本地工作副本已是最新，无需改动")
    elif check_only:
        print(f"共 {len(changes)} 项待更新（--check 模式，未写入）")
    else:
        print(f"已同步 {len(changes)} 项到本地工作副本")
        print("下一步：python scripts/build_knowledge.py 重建知识库索引（含私有笔记）")
    return 0


def push(repo: Path) -> int:
    """把本地工作副本里的个人内容推回私有库（反向同步）。"""
    touched: list[Path] = []

    for src_rel, dst_rel in FILE_MAP:
        src = ROOT.joinpath(*dst_rel.split("/"))
        dst = pdir(repo, src_rel)
        if not src.exists():
            print(f"  ! 本地没有 {dst_rel}，跳过")
            continue
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        touched.append(dst)
        print(f"  → {src_rel}")

    for src_rel, dst_rel in DIR_MAP:
        src_dir = ROOT.joinpath(*dst_rel.split("/"))
        dst_dir = pdir(repo, src_rel)
        if not src_dir.is_dir():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        want = {p.name: p for p in src_dir.glob("*.md")}
        have = {p.name: p for p in dst_dir.glob("*.md")}
        for name in sorted(set(want) | set(have)):
            if name in have and name not in want:
                (dst_dir / name).unlink()
                print(f"  - {src_rel}/{name}")
                touched.append(dst_dir / name)
            elif name not in have or not filecmp.cmp(want[name], have[name], shallow=False):
                shutil.copy2(want[name], dst_dir / name)
                print(f"  → {src_rel}/{name}")
                touched.append(dst_dir / name)

    if not touched:
        print("私有库已是最新，无需提交")
        return 0

    git(repo, "add", "-A")
    rc, out = git(repo, "commit", "-m", "笔记: 从本地工作副本同步")
    print(f"[commit] {out.splitlines()[0] if out else ''}")
    rc, out = git(repo, "push")
    print(f"[push]   {'ok' if rc == 0 else '失败: ' + out}")
    return 0 if rc == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="同步私有库的个人内容到本地工作副本")
    ap.add_argument("--dir", default=None, help="私有库工作副本路径")
    ap.add_argument("--check", action="store_true", help="只报告差异，不写文件")
    ap.add_argument("--push", action="store_true", help="反向：本地 -> 私有库")
    args = ap.parse_args()

    repo = private_dir(args.dir)
    print(f"私有库工作副本: {repo}")
    if not (repo / ".git").exists():
        print(f"\n找不到私有库工作副本。请先 clone：")
        print(f"  git clone https://github.com/Zfeng08/work-buddy-private.git \"{repo}\"")
        return 1
    print()

    return push(repo) if args.push else pull(repo, args.check)


if __name__ == "__main__":
    sys.exit(main())
