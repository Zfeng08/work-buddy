"""公共工具：配置读取、安全写 JSON、带 UA 的 HTTP 请求。"""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 统一写北京时间（UTC+8）的带时区时间戳。
# GitHub Actions 的 runner 是 UTC，若用 localtime 输出，前端算出的
# 「数据距今多久」会偏差 8 小时，看起来像数据一直没更新。
CST = timezone(timedelta(hours=8))

ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def load_config():
    with open(ROOT / "config" / "sources.json", encoding="utf-8") as f:
        return json.load(f)


def load_old(name):
    """读取旧数据，不存在返回 None。"""
    path = ROOT / "data" / f"{name}.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def now_cst():
    """当前北京时间，ISO8601 带时区偏移，如 2026-08-31T16:43:09+08:00。"""
    return datetime.now(CST).isoformat(timespec="seconds")


def save_data(name, payload):
    """写入 data/<name>.json，带 fetched_at 时间戳。"""
    path = ROOT / "data" / f"{name}.json"
    payload["fetched_at"] = now_cst()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] data/{name}.json 已更新 ({payload['fetched_at']})")


def http_get(url, timeout=20, retries=2):
    import requests

    last_err = None
    for i in range(retries + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(2)
    raise last_err


def strip_html(text):
    import re

    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()
