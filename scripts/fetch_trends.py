"""抓取 GitHub Trending，翻译简介、累积历史快照，写入 data/trends.json 与 data/trends_history.json。

数据流：
    GitHub Trending 页面  →  本脚本  →  data/trends.json（当日榜单，含中文简介）
                                      →  data/trends_history.json（最近 30 天快照，用于纵向追踪）
"""
import html
import json
import re
import sys
from datetime import timedelta

from common import CST, ROOT, http_get, load_config, load_old, save_data

REPO_RE = re.compile(r'href="/([^"]+?)"[^>]*data-view-component="true"', re.S)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]{3,}")

HISTORY_DAYS = 30
CACHE_PATH = ROOT / "data" / "trends.json"


# ---------- 简介翻译 ----------
def needs_translation(text):
    """英文为主、几乎没有中文的简介才翻；纯中文/纯符号的跳过。"""
    if not text or not LATIN_RE.search(text):
        return False
    cjk = len(CJK_RE.findall(text))
    return cjk / max(1, len(text)) < 0.2


def translate_google(text):
    url = (
        "https://translate.googleapis.com/translate_a/single"
        "?client=gtx&sl=en&tl=zh-CN&dt=t&q=" + _quote(text)
    )
    data = json.loads(http_get(url, timeout=6, retries=0).text)
    return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()


def translate_mymemory(text):
    url = (
        "https://api.mymemory.translated.net/get?q=" + _quote(text[:480]) + "&langpair=en|zh-CN"
    )
    data = json.loads(http_get(url, timeout=10, retries=1).text)
    out = (data.get("responseData") or {}).get("translatedText") or ""
    return html.unescape(out).strip()


def _quote(s):
    from urllib.parse import quote

    return quote(s, safe="")


_google_disabled = False


def translate(text):
    """多 provider 兜底：Google → MyMemory；都失败返回空串（前端回落英文原文）。

    Google 在境内不可达，失败一次就本轮不再尝试，避免 25 条简介每条都等超时。
    """
    global _google_disabled
    providers = [] if _google_disabled else [translate_google]
    providers.append(translate_mymemory)
    for fn in providers:
        try:
            out = fn(text)
            if out and CJK_RE.search(out):
                return out
        except Exception as e:
            if fn is translate_google:
                _google_disabled = True
            print(f"[warn] 翻译失败({fn.__name__}): {e}")
    return ""


def load_translation_cache():
    """上一次的 trends.json 里已经翻好的简介，简介没变就直接复用，省调用。"""
    old = load_old("trends") or {}
    return {
        (r.get("full_name"), r.get("description")): r.get("description_zh", "")
        for r in old.get("repos", [])
        if r.get("description_zh")
    }


# ---------- 抓取 ----------
def fetch_trending(language):
    url = "https://github.com/trending" + (f"/{language}" if language else "")
    page = http_get(url).text
    repos = []
    for block in re.findall(r'<article class="Box-row">(.*?)</article>', page, re.S):
        m = re.search(r'<h2[^>]*>.*?href="/([^"]+)"', block, re.S)
        if not m:
            continue
        full_name = m.group(1).strip().strip("/")
        desc_m = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', block, re.S)
        desc = html.unescape(re.sub(r"<[^>]+>", "", desc_m.group(1))).strip() if desc_m else ""
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


# ---------- 历史与纵向指标 ----------
def history_path():
    return ROOT / "data" / "trends_history.json"


def load_history():
    path = history_path()
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return (json.load(f).get("days") or [])
    except Exception:
        return []


def annotate(repos, history, today):
    """给每个仓库补上：连续在榜天数、是否新上榜、7 天前的星数差。"""
    past = [d for d in history if d.get("date") != today]
    past.sort(key=lambda d: d.get("date", ""))
    for r in repos:
        streak = 1
        for day in reversed(past):
            if any(x.get("full_name") == r["full_name"] for x in day.get("repos", [])):
                streak += 1
            else:
                break
        r["streak"] = streak
        r["is_new"] = streak == 1

        week_ago = None
        for day in past:
            if today and day.get("date", "") <= _shift(today, -7):
                for x in day.get("repos", []):
                    if x.get("full_name") == r["full_name"]:
                        week_ago = x.get("stars")
        if week_ago is not None and r["stars"] > week_ago:
            r["stars_7d"] = r["stars"] - week_ago
    return repos


def _shift(day, delta):
    from datetime import date

    y, m, d = (int(x) for x in day.split("-"))
    return str(date(y, m, d) + timedelta(days=delta))


def update_history(repos, today):
    days = [d for d in load_history() if d.get("date") != today]
    days.append({
        "date": today,
        "repos": [
            {"full_name": r["full_name"], "stars": r["stars"], "stars_today": r["stars_today"]}
            for r in repos
        ],
    })
    days.sort(key=lambda d: d.get("date", ""))
    days = days[-HISTORY_DAYS:]
    path = history_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, ensure_ascii=False, indent=2)
    print(f"[ok] data/trends_history.json 已更新（{len(days)} 天）")
    return days


# ---------- 主流程 ----------
def main():
    cfg = load_config()["trends"]
    all_repos, seen, ok = [], set(), False

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
        if load_old("trends"):
            print("[warn] 全部失败，保留旧数据")
        return 0

    all_repos.sort(key=lambda x: x["stars_today"], reverse=True)
    all_repos = all_repos[: cfg["max_repos"]]

    # 翻译简介（带跨天缓存，简介没变不重复调用）
    cache = load_translation_cache()
    for r in all_repos:
        cached = cache.get((r["full_name"], r["description"]))
        if cached:
            r["description_zh"] = cached
        elif needs_translation(r["description"]):
            zh = translate(r["description"])
            if zh:
                r["description_zh"] = zh

    today = __import__("datetime").datetime.now(CST).date().isoformat()
    history = load_history()
    all_repos = annotate(all_repos, history, today)
    days = update_history(all_repos, today)

    save_data("trends", {
        "repos": all_repos,
        "count": len(all_repos),
        "tracking_days": len(days),
        "date": today,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
