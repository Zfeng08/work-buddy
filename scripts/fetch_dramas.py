# -*- coding: utf-8 -*-
"""剧集采集：优酷 / 爱奇艺 / 腾讯视频「正在播什么」+ 豆瓣评分。

数据源（2026-09 实测可用，均为公开接口，无需登录）：
  爱奇艺：https://pcw-api.iqiyi.com/search/recommend/list?channel_id=2   （2=电视剧频道）
          period 字段=开播日期，是判断"新剧/在播"的天然依据
  优酷　：https://search.youku.com/api/search?keyword=电视剧            （公开搜索，免签名）
          feature 字段形如 "2026 · 电视剧 · 中国 · 更新至12集"
  腾讯　：https://pbaccess.video.qq.com/trpc.videosearch.hot_rank.../HotRankHttp （剧集热榜）
  豆瓣　：https://movie.douban.com/j/search_subjects                     （评分库，每 tag 100 部）

关于豆瓣：m 站的 rexxar 接口对高频请求会 403，而 movie.douban.com 的
j/search_subjects 稳定得多（实测 6 连发零限流），且一次返回 100 部带评分
的剧集，用它建评分映射比逐部搜索靠谱得多。
"""
import re
import time
from datetime import datetime, timedelta

import requests

from common import UA, load_config, save_data

PLATFORM_META = {
    "youku":   {"name": "优酷",     "color": "#1f8ff9", "home": "https://www.youku.com/"},
    "iqiyi":   {"name": "爱奇艺",   "color": "#00be06", "home": "https://www.iqiyi.com/"},
    "tencent": {"name": "腾讯视频", "color": "#ff9c19", "home": "https://v.qq.com/"},
}

# 豆瓣评分库标签（每个 tag 返回 100 部，按推荐度=热度排序）
DOUBAN_TAGS = ["热门", "国产剧", "美剧", "日剧", "韩剧", "英剧"]

# 优酷搜索结果里混入的非剧集内容
NOT_DRAMA = re.compile(r"盛典|颁奖|预告|花絮|片花|特辑|盘点|指南|合集|访谈|纪录片|综艺|动漫|少儿|晚会|直击|纯享|解说")


def _get(url, params=None, headers=None, timeout=25, retries=2):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    last = None
    for i in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code in (403, 429):
                last = RuntimeError(f"{r.status_code} 限流")
                if i < retries:
                    time.sleep(3 * (i + 1))
                continue
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(1.5)
    raise last


def _norm(t):
    """标题归一化：去季数/括号/标点，用于跨源匹配。"""
    t = t or ""
    t = re.sub(r"[（(【\[].*?[)）】\]]", "", t)
    t = re.sub(r"第[一二三四五六七八九十\d]+季", "", t)
    t = re.sub(r"[\s·:：\-—–_！!？?、,，.。'\"“”‘’/|​]+", "", t)
    return t.strip().lower()


# ---------------------------------------------------------------- 豆瓣评分库

def fetch_douban_map(tags=None):
    """豆瓣剧集评分库：多 tag 各取 100 部，建 归一化剧名 → 评分信息 映射。"""
    out = {}
    tags = tags or DOUBAN_TAGS
    for idx, tag in enumerate(tags):
        if idx:
            time.sleep(1.0)
        try:
            r = _get("https://movie.douban.com/j/search_subjects",
                     params={"type": "tv", "tag": tag, "sort": "recommend",
                             "page_limit": 100, "page_start": 0},
                     headers={"Referer": "https://movie.douban.com/tv/"}, timeout=25)
            subjects = r.json().get("subjects", [])
        except Exception as e:
            print(f"  [warn] 豆瓣 tag={tag} 失败: {e}")
            continue
        for s in subjects:
            title = s.get("title") or ""
            key = _norm(title)
            if not key:
                continue
            rate = s.get("rate") or ""
            try:
                rating = float(rate) if rate else None
            except Exception:
                rating = None
            info = {
                "douban_id": s.get("id"),
                "douban_title": title,
                "douban_rating": rating,
                "douban_cover": s.get("cover") or "",
                "douban_url": s.get("url") or f"https://movie.douban.com/subject/{s.get('id')}/",
                "episodes_info": s.get("episodes_info") or "",
                "is_new": bool(s.get("is_new")),
            }
            old = out.get(key)
            if not old or (not old.get("douban_rating") and rating):
                out[key] = info
        print(f"  豆瓣 tag={tag}: {len(subjects)} 部")
    print(f"  豆瓣评分库: {len(out)} 部（有评分 {sum(1 for v in out.values() if v['douban_rating'])} 部）")
    return out


def match_douban(title, db):
    """在豆瓣评分库里匹配剧名：先精确，再严格包含。"""
    key = _norm(title)
    if key in db:
        return db[key]
    if len(key) < 4:
        return None
    for k, v in db.items():
        if abs(len(k) - len(key)) > 2:
            continue
        if k in key or key in k:
            return v
    return None


def year_of(title):
    """[保留] 豆瓣年份查询接口（rexxar / subject_suggest）已加反爬，
    实测 403/空列表，故当前不用于过滤；如需恢复可在此接入其它数据源。"""
    return None


# ---------------------------------------------------------------- 爱奇艺

def fetch_iqiyi(pages=3, ret_num=30, days=150):
    """爱奇艺电视剧频道，用 period（开播日期）过滤近期新剧。"""
    items, seen = [], set()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for page in range(1, pages + 1):
        try:
            r = _get("https://pcw-api.iqiyi.com/search/recommend/list",
                     params={"channel_id": 2, "data_type": 1, "mode": 11,
                             "page_id": page, "ret_num": ret_num, "session": ""})
            lst = r.json().get("data", {}).get("list", [])
        except Exception as e:
            print(f"  [warn] 爱奇艺第{page}页失败: {e}")
            continue
        if not lst:
            break
        for it in lst:
            name = (it.get("name") or "").strip()
            if not name or name in seen:
                continue
            period = (it.get("period") or "").strip()
            if period and period < cutoff:
                continue
            seen.add(name)
            total = it.get("videoCount") or 0
            latest = it.get("latestOrder") or 0
            if total and latest < total:
                status, on_air = f"更新至{latest}集 / 共{total}集", True
            elif total:
                status, on_air = f"全{total}集", False
            else:
                status, on_air = "", False
            people = (it.get("people") or {}).get("main_charactor") or []
            items.append({
                "title": name, "platform": "iqiyi",
                "cover": it.get("imageUrl") or "",
                "url": it.get("playUrl") or f"https://www.iqiyi.com/a_{it.get('albumId')}.html",
                "status": status, "on_air": on_air, "episodes": total,
                "categories": it.get("categories") or [],
                "desc": (it.get("description") or "").strip(),
                "actors": [p.get("name") for p in people[:4] if p.get("name")],
                "premiere": period,
                "year": int(period[:4]) if re.match(r"^\d{4}", period) else None,
                "rank": len(items) + 1,
            })
        time.sleep(0.4)
    print(f"  爱奇艺: {len(items)} 部（近 {days} 天开播）")
    return items


# ---------------------------------------------------------------- 优酷

def _youku_walk(node, out):
    """递归遍历优酷 originNodes，抽出剧集卡。"""
    if isinstance(node, dict):
        data = node.get("data")
        if isinstance(data, dict) and data.get("feature") and data.get("showId"):
            ti = (((data.get("action") or {}).get("report") or {}).get("trackInfo")) or {}
            title = ti.get("object_title") or data.get("title")
            if title:
                out.append({"data": data, "title": title})
        for v in node.values():
            _youku_walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _youku_walk(v, out)


def _parse_youku_feature(feature):
    """"2026 · 电视剧 · 中国 · 更新至12集" -> (year, status, on_air)"""
    parts = [p.strip() for p in (feature or "").split("·")]
    year = None
    for p in parts:
        if re.fullmatch(r"(19|20)\d{2}", p):
            year = int(p)
            break
    status, on_air = "", False
    m = re.search(r"(更新至\s*\d+\s*集|全\s*\d+\s*集|共\s*\d+\s*集|\d+\s*集全)", feature or "")
    if m:
        status = re.sub(r"\s+", "", m.group(1))
        on_air = "更新至" in status
    if "完结" in (feature or ""):
        on_air = False
    return year, status, on_air


def fetch_youku(pages=3, pz=30, min_year=2025):
    """优酷搜索「电视剧」，过滤非剧集内容与老剧。"""
    items, seen = [], set()
    for page in range(1, pages + 1):
        try:
            r = _get("https://search.youku.com/api/search",
                     params={"keyword": "电视剧", "pg": page, "pz": pz}, timeout=30)
            nodes = r.json().get("originNodes", [])
        except Exception as e:
            print(f"  [warn] 优酷第{page}页失败: {e}")
            continue
        found = []
        _youku_walk(nodes, found)
        if not found:
            break
        for f in found:
            d, title = f["data"], f["title"]
            if title in seen or NOT_DRAMA.search(title):
                continue
            year, status, on_air = _parse_youku_feature(d.get("feature"))
            if year and year < min_year:
                continue
            eps = d.get("episodeTotal") or 0
            if eps and eps <= 4:
                continue
            seen.add(title)
            parts = [p.strip() for p in (d.get("feature") or "").split("·")]
            cats = [parts[1]] if len(parts) > 1 and parts[1] != "电视剧" else []
            items.append({
                "title": title, "platform": "youku",
                "cover": "", "url": f"https://www.youku.com/v_show/id_{d.get('showId')}.html",
                "status": status, "on_air": on_air, "episodes": eps,
                "categories": cats, "desc": "", "actors": [],
                "premiere": "", "year": year, "rank": len(items) + 1,
            })
        time.sleep(0.6)
    print(f"  优酷: {len(items)} 部（{min_year} 年后）")
    return items


# ---------------------------------------------------------------- 腾讯视频

def fetch_tencent(limit=30):
    """腾讯视频剧集热榜（当下热度排序）。"""
    url = "https://pbaccess.video.qq.com/trpc.videosearch.hot_rank.HotRankServantHttp/HotRankHttp"
    try:
        r = requests.post(url, json={"page_num": 0, "page_size": limit, "scene": 1, "rank_type": 1},
                          headers={"User-Agent": UA, "content-type": "application/json"}, timeout=25)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        print(f"  [warn] 腾讯热榜失败: {e}")
        return []

    items = []
    for nav in d.get("data", {}).get("navItemList", []):
        if nav.get("tabName") != "电视剧":
            continue
        for i, it in enumerate(nav.get("hotRankResult", {}).get("rankItemList", []), 1):
            title = (it.get("title") or "").strip()
            if not title:
                continue
            items.append({
                "title": title, "platform": "tencent",
                "cover": it.get("imgUrl") or "", "url": it.get("url") or "",
                "status": "", "on_air": False, "episodes": 0,
                "categories": [], "desc": "", "actors": [],
                "premiere": "", "year": None, "rank": i, "hot": True,
            })
    print(f"  腾讯视频: {len(items)} 部")
    return items


# ---------------------------------------------------------------- 合并

def main():
    print("[dramas] 开始采集…")
    cfg = load_config().get("dramas", {})
    db = fetch_douban_map(cfg.get("tags"))

    per_platform = {}
    for pid, fn in (("youku", fetch_youku), ("iqiyi", fetch_iqiyi), ("tencent", fetch_tencent)):
        try:
            per_platform[pid] = fn(**dict(cfg.get(pid) or {}))
        except Exception as e:
            print(f"  [error] {pid} 采集异常: {e}")
            per_platform[pid] = []

    # 合并去重
    merged = {}
    for pid, lst in per_platform.items():
        for it in lst:
            key = _norm(it["title"])
            if not key:
                continue
            if key not in merged:
                merged[key] = {
                    "title": it["title"], "platforms": [], "cover": "", "url": "",
                    "status": "", "on_air": False, "episodes": 0, "categories": [],
                    "desc": "", "actors": [], "premiere": "", "year": it.get("year"),
                    "rank": {}, "douban": None, "hot": False,
                }
            m = merged[key]
            if pid not in m["platforms"]:
                m["platforms"].append(pid)
            m["rank"][pid] = it.get("rank")
            for f in ("cover", "url", "status", "desc", "premiere"):
                if not m.get(f) and it.get(f):
                    m[f] = it[f]
            m["on_air"] = m["on_air"] or bool(it.get("on_air"))
            m["hot"] = m["hot"] or bool(it.get("hot"))
            if not m["episodes"] and it.get("episodes"):
                m["episodes"] = it["episodes"]
            if not m["categories"] and it.get("categories"):
                m["categories"] = it["categories"]
            if not m["actors"] and it.get("actors"):
                m["actors"] = it["actors"]
            if not m["year"] and it.get("year"):
                m["year"] = it["year"]

    # 补豆瓣评分
    hit = 0
    for key, m in merged.items():
        info = match_douban(m["title"], db)
        if not info:
            continue
        hit += 1
        m["douban"] = info
        if info.get("episodes_info") and not m["status"]:
            m["status"] = info["episodes_info"]
        if info.get("episodes_info") and "更新至" in info["episodes_info"]:
            m["on_air"] = True
        if info.get("douban_cover") and not m["cover"]:
            m["cover"] = info["douban_cover"]
        if info.get("is_new"):
            m["is_new"] = True
    print(f"  豆瓣评分匹配: {hit} / {len(merged)}")

    # 剔除确认的老剧（年份 < 2024）。腾讯热榜无年份字段，
    # 豆瓣的搜索端点（rexxar / subject_suggest）已加入反爬，
    # 不再依赖它做年份核验，靠前端筛选与排序来弱化老剧干扰。
    def keep(it):
        y = it.get("year")
        if y:
            try:
                return int(y) >= 2024
            except Exception:
                return True
        return True
    all_items = [it for it in merged.values() if keep(it)]

    def score(it):
        d = (it.get("douban") or {}).get("douban_rating") or 0
        return (1 if it.get("on_air") else 0, d)
    all_items.sort(key=score, reverse=True)

    platforms = {}
    for pid, meta in PLATFORM_META.items():
        lst = [it for it in all_items if pid in it["platforms"]]
        lst.sort(key=lambda x: x["rank"].get(pid) or 999)
        platforms[pid] = {**meta, "id": pid, "count": len(lst), "items": lst}

    payload = {
        "count": len(all_items),
        "on_air_count": sum(1 for it in all_items if it.get("on_air")),
        "rated_count": sum(1 for it in all_items if (it.get("douban") or {}).get("douban_rating")),
        "platforms": platforms,
        "items": all_items,
    }
    save_data("dramas", payload)
    print(f"[ok] 共 {len(all_items)} 部 | 更新中 {payload['on_air_count']} | 有豆瓣评分 {payload['rated_count']}")


if __name__ == "__main__":
    main()
