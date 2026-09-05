"""通过腾讯行情接口抓取指数/汇率快照，写入 data/finance.json。

接口返回格式（~ 分隔）：
v_sh000001="1~上证指数~000001~3398.08~...~涨跌~涨跌幅~...";
关键字段：1=名称 3=最新价 4=昨收 31=涨跌 32=涨跌幅
"""
import sys

from common import http_get, load_config, load_old, save_data


def parse_line(line, is_fx=False):
    fields = line.split("~")
    if len(fields) < (14 if is_fx else 33):
        return None
    try:
        if is_fx:
            # 外汇格式：1=名称 3=最新价 12=涨跌 13=涨跌幅
            price = float(fields[3])
            change = float(fields[12])
            change_pct = float(fields[13])
        else:
            price = float(fields[3])
            change = float(fields[31])
            change_pct = float(fields[32])
    except (ValueError, IndexError):
        return None
    return {
        "name": fields[1],
        "price": price,
        "change": change,
        "change_pct": change_pct,
    }


def main():
    cfg = load_config()["finance"]
    codes = [s["code"] for s in cfg["symbols"]]
    quotes = []
    try:
        resp = http_get("https://qt.gtimg.cn/q=" + ",".join(codes))
        text = resp.content.decode("gbk", errors="ignore")
        for line in text.strip().split(";"):
            line = line.strip()
            if "=" not in line:
                continue
            var, payload = line.split("=", 1)
            q = parse_line(payload.strip('"'), is_fx="wh" in var)
            if q:
                quotes.append(q)
    except Exception as e:
        print(f"[err] 行情接口失败: {e}")

    if not quotes:
        old = load_old("finance")
        if old:
            print("[warn] 接口失败，保留旧数据")
            return 0
        save_data("finance", {"quotes": []})
        return 0

    # 保留最近 90 天的历史序列（供页面画趋势）
    old = load_old("finance") or {}
    history = old.get("history", [])
    today = __import__("time").strftime("%Y-%m-%d")
    history.append({"date": today, "quotes": quotes})
    # 同日多次执行只保留最新一份
    dedup = {}
    for h in history:
        dedup[h["date"]] = h
    history = sorted(dedup.values(), key=lambda x: x["date"])[-90:]

    save_data("finance", {"quotes": quotes, "history": history})
    return 0


if __name__ == "__main__":
    sys.exit(main())
