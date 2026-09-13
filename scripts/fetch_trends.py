"""抓取 GitHub Trending 仓库列表，写入 data/trends.json。"""
import re
import sys

from common import http_get, load_config, load_old, save_data

REPO_RE = re.compile(r'href="/([^"]+?)"[^>]*data-view-component="true"', re.S)


def fetch_trending(language):
    url = "https://github.com/trending" + (f"/{language}" if language else "")
    html = http_get(url).text
    repos = []
    # 每个 article 块是一个仓库
    for block in re.findall(r'<article class="Box-row">(.*?)</article>', html, re.S):
        m = re.search(r'<h2[^>]*>.*?href="/([^"]+)"', block, re.S)
        if not m:
            continue
        full_name = m.group(1).strip().strip("/")
        desc_m = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', block, re.S)
        desc = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip() if desc_m else ""
        stars_m = re.search(r'href="/[^"]+/stargazers"[^>]*>.*?</svg>\s*([\d,]+)', block, re.S)
        stars = int(stars_m.group(1).replace(",", "")) if stars_m else 0
        today_m = re.search(r'([\d,]+)\s+stars today', block)
        stars_today = int(today_m.group(1).replace(",", "")) if today_m else 0
        lang_m = re.search(r'itemprop="programmingLanguage">([^<]+)<', block)
        repos.append({
            "full_name": full_name,
            "url": f"https://github.com/{full_name}",
            "description": desc,
            "stars": stars,
            "stars_today": stars_today,
            "language": lang_m.group(1) if lang_m else (language or "—"),
        })
    return repos


def main():
    cfg = load_config()["trends"]
    all_repos = []
    seen = set()
    ok = False
    for lang in cfg["languages"]:
        label = lang or "all"
        try:
            repos = fetch_trending(lang)
            for r in repos:
                if r["full_name"] not in seen:
                    seen.add(r["full_name"])
                    all_repos.append(r)
            print(f"[ok] trending/{label}: {len(repos)} 个仓库")
            ok = ok or bool(repos)
        except Exception as e:
            print(f"[err] trending/{label}: {e}")

    if not ok:
        old = load_old("trends")
        if old:
            print("[warn] 全部失败，保留旧数据")
        return 0

    all_repos.sort(key=lambda x: x["stars_today"], reverse=True)
    save_data("trends", {"repos": all_repos[: cfg["max_repos"]], "count": len(all_repos)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
