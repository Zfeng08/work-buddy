"""知识库分析与关联：解析 knowledge/**/*.md，输出 data/knowledge.json。

解析内容：
- YAML front-matter（title / tags / date / source / keywords）
- 正文中的 [[双向链接]]

关键词与链接化（用户需求驱动）：
- 每篇正文用 jieba.analyse 抽出 topk 关键词（合并 frontmatter 的 keywords）
- 汇总所有笔记的关键词到全局 keyword_index {kw: [note_id...]}
- 渲染正文时，把 keyword_index 里出现的关键词替换成 <a href="#kw-xxx" class="kw">，
  同一段内同一个词只链接首次出现
- 这样在前端：点正文里的词 → 弹层列出含这个词的所有笔记

关联度计算（笔记 A 与 B 的分数）：
- 显式链接 [[B]] 出现在 A 中        +3
- 每个共享标签 / 共享关键词         +1
- 文本 bigram Jaccard 相似度        + 相似度 * 5
分数 >= 2 视为「相关笔记」，同时输出图谱（节点+边）供前端渲染。
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import jieba.analyse

from common import now_cst

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "knowledge"
DATA_PATH = ROOT / "data" / "knowledge.json"

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# jieba 自带的 stop_words 对短句噪音多，自己加一批知识库领域的停用词
STOP_WORDS = set("""
我们 你 您 他 她 它 他们 自己 一个 一些 那种 这个 那个 什么 怎么 为什么 因为 所以
可以 可能 需要 应该 已经 还是 不是 以及 但是 但是 并 并且 或者 也就是 也就是说
会 能 要 没有 真的 好像 大概 大约 非常 很 十分 特别 比较 更 最 极 其 一 一 一
之后 之前 之前 然后 现在 当时 其实 真的 反正 据说 突然 然后 如果 觉得 感到 表示
认为 想 知道 看到 听到 没用 说 没 啊 哈 呀 呢 吧 哦 嗯 啦 吗 嘛
那个 这种 这些 那些 这是 这时 那时 此时 彼此
很多 不少 大部分 小部分 部分 全部 所有 任何 每个 整 一个
""".split())

# 关键词最低入选门槛：全局出现 ≥ MIN_FREQ 次，且至少出现在 MIN_DOCS 篇笔记
MIN_FREQ = 2
MIN_DOCS = 1


def parse_front_matter(fm_text):
    """极简 YAML 子集解析：只支持 key: value 与 key: 列表。"""
    meta = {}
    current_key = None
    for line in fm_text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if current_key:
                val = line.split("-", 1)[1].strip().strip("\"'")
                if isinstance(meta[current_key], list):
                    meta[current_key].append(val)
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip("\"'")
            if val == "":
                meta[key] = []
            elif val.startswith("[") and val.endswith("]"):
                meta[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            else:
                meta[key] = val
            current_key = key
    return meta


def bigrams(text):
    text = re.sub(r"\s+", "", text)
    return {text[i : i + 2] for i in range(len(text) - 1)} if len(text) > 1 else set()


def extract_keywords(text, topk=10):
    """用 jieba TF-IDF 风格从正文抽关键词，过滤停用词与噪音。"""
    if not text or len(text.strip()) < 30:
        return []
    raw = jieba.analyse.extract_tags(text, topK=topk * 2, withWeight=False)
    out = []
    for w in raw:
        w = w.strip()
        if len(w) < 2:                      # 至少 2 字
            continue
        if w in STOP_WORDS:
            continue
        if re.fullmatch(r"[\d\W_]+", w):     # 纯数字/标点
            continue
        out.append(w)
        if len(out) >= topk:
            break
    return out


def load_notes():
    notes = []
    for path in sorted(NOTES_DIR.rglob("*.md")):
        if path.name == "README.md":
            continue
        raw = path.read_text(encoding="utf-8")
        m = FM_RE.match(raw)
        meta = parse_front_matter(m.group(1)) if m else {}
        body = raw[m.end():] if m else raw

        title = meta.get("title") or path.stem
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        kw_meta = meta.get("keywords", [])
        if isinstance(kw_meta, str):
            kw_meta = [kw_meta]
        links = [t.strip() for t in LINK_RE.findall(body)]

        # 合并：frontmatter 给的关键词（用户/AI 标注）+ jieba 从正文抽的
        body_for_extract = re.sub(r"\[\[[^\]]+\]\]", "", body)
        kw_extracted = extract_keywords(body_for_extract, topk=10)
        keywords = []
        for k in list(kw_meta) + kw_extracted:
            k = k.strip()
            if k and k not in keywords:
                keywords.append(k)

        rel = path.relative_to(NOTES_DIR).as_posix()
        notes.append({
            "id": rel,
            "title": title,
            "tags": tags,
            "keywords": keywords,
            "links": links,
            "date": meta.get("date", ""),
            "source": meta.get("source", ""),
            "summary": re.sub(r"\s+", " ", body.strip())[:150],
            "body": body,
            "path": f"knowledge/{rel}",
            "word_count": len(body),
            "_bigrams": bigrams(re.sub(r"\[\[[^\]]+\]\]", "", body)),
        })
    return notes


def build_keyword_index(notes):
    """汇总所有笔记的关键词 → 全局倒排索引 {kw: [{note_id, count}]}。

    count 怎么算：在该笔记正文里该词出现次数（不分大小写，整词匹配）。
    """
    freq = defaultdict(int)        # kw -> 全局出现次数
    docs = defaultdict(set)        # kw -> {note_id}
    for n in notes:
        body = re.sub(r"\[\[[^\]]+\]\]", "", n["body"])
        for kw in n["keywords"]:
            if not kw:
                continue
            cnt = len(re.findall(re.escape(kw), body))
            if cnt == 0:
                continue
            freq[kw] += cnt
            docs[kw].add(n["id"])
    idx = {}
    for kw, f in freq.items():
        if f < MIN_FREQ or len(docs[kw]) < MIN_DOCS:
            continue
        idx[kw] = sorted(
            ({"note_id": nid, "count": sum(
                len(re.findall(re.escape(kw), re.sub(r"\[\[[^\]]+\]\]", "", nn["body"])))
                for nn in notes if nn["id"] == nid)}
             for nid in docs[kw]),
            key=lambda x: -x["count"],
        )
    # 按「覆盖文章数 × 总频次」排序，最有信息量的关键词排前
    items = sorted(idx.items(), key=lambda kv: (-len(kv[1]), -sum(x["count"] for x in kv[1])))
    return dict(items)


def render_body_html(body, keywords):
    """渲染笔记正文为 HTML：[[wiki]] 转链接、# 标题转 h、关键词转可点击链接。

    实现思路：先把会冲突的特殊语法替换成占位符（避免里头的关键词被提前匹配），
    再做 HTML 转义，最后把占位符还原成真实标签。
    """
    # 1. [[wikilink]] → 占位符（标题文本本身不参与关键词链接，否则会出现嵌套 <a>）
    wiki_store = []
    def _wiki(m):
        wiki_store.append(m.group(1).strip())
        return f"\x00WIKI{len(wiki_store) - 1}\x00"
    text = LINK_RE.sub(_wiki, body)

    # 2. markdown 标题 → 占位符（每行处理一次）
    def _md(m):
        n = len(m.group(1))
        return f"\x00H{n}\x00{m.group(2)}"
    text = re.sub(r"^(#{1,6})\s+(.+)$", _md, text, flags=re.M)

    # 3. 切段（保留段落分隔符）
    paragraphs = re.split(r"(\n\s*\n)", text)

    kws = sorted(keywords, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in kws)) if kws else None

    out = []
    for p in paragraphs:
        if p.strip() == "":
            out.append(p)
            continue
        # 先 HTML 转义（防 XSS）
        escaped = esc(p)
        # 关键词替换：段内首次出现才链接
        if pattern:
            seen = set()
            def _repl(m):
                k = m.group(0)
                if k in seen:
                    return k
                seen.add(k)
                return f'<a class="kw" href="#kw-{urllib_quote(k)}" data-kw="{esc_attr(k)}">{k}</a>'
            escaped = pattern.sub(_repl, escaped)
        # wikilink 还原
        for i, title in enumerate(wiki_store):
            escaped = escaped.replace(
                f"\x00WIKI{i}\x00",
                f'<a class="wikilink" href="#note-{urllib_quote(title)}">{esc(title)}</a>',
            )
        # markdown 标题还原（1~6 级）
        for lvl in range(1, 7):
            escaped = re.sub(rf"\x00H{lvl}\x00(.+?)(?=<br>|$)",
                             lambda m, lvl=lvl: f"<h{lvl}>{m.group(1)}</h{lvl}>", escaped)
        # 段内换行
        out.append(escaped.replace("\n", "<br>"))

    return "".join(out)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
              .replace('"', "&quot;"))


def esc_attr(s):
    return esc(s).replace("'", "&#39;")


def urllib_quote(s):
    # 关键词进 URL 用百分号编码（前端 decode 后查 keyword_index）
    import urllib.parse
    return urllib.parse.quote(s)


def build_relations(notes):
    by_title = {n["title"]: n for n in notes}
    edges = []
    for i, a in enumerate(notes):
        for b in notes[i + 1:]:
            score = 0.0
            reasons = []
            if b["title"] in a["links"] or a["title"] in b["links"]:
                score += 3
                reasons.append("双向链接")
            shared = set(a["tags"]) & set(b["tags"])
            if shared:
                score += 2 * len(shared)
                reasons.append(f"共同标签: {', '.join(sorted(shared))}")
            shared_kw = set(a.get("keywords", [])) & set(b.get("keywords", []))
            if shared_kw:
                score += 1 * len(shared_kw)
                reasons.append(f"共享关键词 {len(shared_kw)} 个")
            union = a["_bigrams"] | b["_bigrams"]
            if union:
                sim = len(a["_bigrams"] & b["_bigrams"]) / len(union)
                if sim >= 0.05:
                    score += sim * 5
                    reasons.append(f"内容相似 {sim:.0%}")
            if score >= 2:
                edges.append({
                    "source": a["id"],
                    "target": b["id"],
                    "score": round(score, 2),
                    "reasons": reasons,
                })
    edges.sort(key=lambda e: e["score"], reverse=True)
    return edges


def main():
    notes = load_notes()

    # 全局关键词索引
    kw_index = build_keyword_index(notes)
    valid_kws = set(kw_index.keys())

    # 给每篇笔记渲染正文 HTML（用 valid_kws 而非每篇自己的 keywords，确保跨文章链接一致）
    for n in notes:
        n["body_html"] = render_body_html(n["body"], valid_kws)
        n["body_size"] = len(n["body"])

    edges = build_relations(load_notes())  # 重新加载以保留 bigrams

    # 每篇笔记的相关推荐（取分数最高的前 5）
    related = {n["id"]: [] for n in notes}
    for e in edges:
        related[e["source"]].append({"id": e["target"], "score": e["score"], "reasons": e["reasons"]})
        related[e["target"]].append({"id": e["source"], "score": e["score"], "reasons": e["reasons"]})
    for k in related:
        related[k] = sorted(related[k], key=lambda x: -x["score"])[:5]

    tag_index = {}
    for n in notes:
        for t in n["tags"]:
            tag_index.setdefault(t, []).append(n["id"])

    # 输出精简版笔记（去掉 _bigrams 与原文 body，省体积；body_html 足够前端展示）
    notes_out = []
    for n in notes:
        notes_out.append({
            "id": n["id"],
            "title": n["title"],
            "tags": n["tags"],
            "keywords": n["keywords"],
            "links": n["links"],
            "date": n["date"],
            "source": n["source"],
            "summary": n["summary"],
            "path": n["path"],
            "word_count": n["word_count"],
            "body_html": n["body_html"],
        })

    graph = {
        "nodes": [
            {
                "id": n["id"],
                "name": n["title"],
                "value": len(n["tags"]) + 1,
                "tags": n["tags"],
                "symbolSize": min(20 + 6 * len(n["tags"]), 50),
                "category": n["tags"][0] if n["tags"] else "未分类",
            }
            for n in notes
        ],
        "links": [{"source": e["source"], "target": e["target"], "value": e["score"]} for e in edges],
    }

    DATA_PATH.parent.mkdir(exist_ok=True)
    payload = {
        "notes": notes_out,
        "edges": edges,
        "related": related,
        "tag_index": tag_index,
        "keyword_index": kw_index,
        "graph": graph,
        "stats": {
            "note_count": len(notes),
            "tag_count": len(tag_index),
            "link_count": len(edges),
            "keyword_count": len(kw_index),
        },
        "fetched_at": now_cst(),
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] 知识库分析完成: {len(notes)} 篇笔记, {len(kw_index)} 个关键词, "
          f"{len(edges)} 条关联, {len(tag_index)} 个标签")
    return 0


if __name__ == "__main__":
    sys.exit(main())