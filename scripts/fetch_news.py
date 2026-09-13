"""抓取 RSS 资讯源，去重合并后写入 data/news.json。"""
import sys

import feedparser

from common import http_get, load_config, load_old, save_data, strip_html


def fetch_all():
    cfg = load_config()["news"]
    items = []
    seen_links = set()
    errors = []

    for src in cfg["sources"]:
        try:
            resp = http_get(src["url"])
            feed = feedparser.parse(resp.content)
            count = 0
            for entry in feed.entries:
                link = entry.get("link", "")
                if link in seen_links:
                    continue
                seen_links.add(link)
                items.append({
                    "title": strip_html(entry.get("title", "")),
                    "link": link,
                    "summary": strip_html(entry.get("summary", ""))[:200],
                    "source": src["name"],
                    "category": src.get("category", ""),
                    "published": entry.get("published", "") or entry.get("updated", ""),
                })
                count += 1
                if count >= cfg["max_items_per_source"]:
                    break
            print(f"[ok] {src['name']}: {count} 条")
        except Exception as e:
            errors.append(f"{src['name']}: {e}")
            print(f"[err] {src['name']}: {e}")

    if not items:
        return None, errors

    items = items[: cfg["max_total"]]
    return {"items": items, "count": len(items), "sources_ok": len(cfg["sources"]) - len(errors)}, errors


def main():
    data, errors = fetch_all()
    if data is None:
        old = load_old("news")
        if old:
            print("[warn] 全部源失败，保留旧数据")
        else:
            save_data("news", {"items": [], "count": 0, "sources_ok": 0, "errors": errors})
        return 0
    data["errors"] = errors
    save_data("news", data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
