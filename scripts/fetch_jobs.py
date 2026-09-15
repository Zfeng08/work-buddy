"""抓取制造业工厂供应链/计划岗（成都、昆明、江浙沪），写入 data/jobs.json。

数据源：猎聘按「城市 + 职业分类」的公开 SEO 聚合页（SSR 直出 HTML，无反爬）。
  - career/PMC          = 生产计划 / 物料管理（工厂计划专员/主管的标准叫法）
  - career/gongyinglian = 供应链
  - career/caigou       = 采购（供应链相邻方向，已实测可抓；wuliu/cangchu 无此页）

为什么不用远程岗源（V2EX/电鸭/Jobicy）：
  用户要的是「去工厂」的计划岗（PMC / 需求计划 / 物料计划），这类岗位天然
  需要现场协同，几乎不会远程发布；且国内主流招聘站（智联/BOSS/前程）都反爬，
  只有猎聘的 SEO 页和各地公共招聘网可直接抓。

分级规则（写入 tier 字段，前端据此排序展示）：
  core    岗位名命中「计划 / PMC / 物料 / 排产 / 物控 / 排程 / 生产控制」等
  related 岗位名命中「供应链 / 采购 / 物流 / 仓储 / 库存」等相邻方向
  明显不对口的（行政 / 销售 / 客服 / 操作工 / 仓库管理员等）直接丢弃

领域规则（写入 domain 字段，前端据此筛选）：
  取自猎聘卡片的 company-tags-box 首段（公司行业，如「电子/半导体/集成电路」），
  再归一化到 11 个领域。不用关键词猜公司名——猎聘大量公司匿名成「某知名公司」，
  但行业字段始终带，是唯一可信的行业来源。
"""
import collections
import re
import sys
import time

from bs4 import BeautifulSoup

from common import http_get, load_config, load_old, save_data

# 岗位名命中这些 → 核心岗（计划方向）
CORE_PAT = re.compile(
    r"计划|pmc|物料|物控|排产|排程|生产控制|生产调度|交付计划|"
    r"需求计划|生产计划|物料计划|采购计划|planner|mrp|s&op|sop|demand planning",
    re.IGNORECASE,
)
# 岗位名命中这些 → 相邻方向（供应链）
RELATED_PAT = re.compile(
    r"供应链|采购|物流|仓储|库存|supply chain|procurement|sourcing|"
    r"logistic|inventory|warehouse|需求预测|产销",
    re.IGNORECASE,
)
# 岗位名命中这些 → 明显不对口，丢弃（PMC 分类下会混入行政/仓储/操作工）
BLOCK_PAT = re.compile(
    r"仓库管理员|仓管|行政|前台|司机|操作工|普工|保安|保洁|销售|客服|运营|"
    r"人力资源|财务|出纳|会计|法务|it支持|网络管理|平面设计|厨师|服务员|搬运|"
    r"叉车|质检员|检验员|技术员|工程师$",
    re.IGNORECASE,
)

# 经验/学历标签识别（labels-tag 里混着福利标签，靠正则区分）
EXP_PAT = re.compile(r"(\d+\s*年|经验不限|应届|在校|实习)")
EDU_PAT = re.compile(r"(大专|本科|硕士|博士|学历不限|mba|高中|中专)", re.IGNORECASE)

# 行业归一化：猎聘原始行业词 -> 11 个领域
# 匹配时优先用逗号前的第一段（主行业），匹配不到再拿整串兜底。
DOMAIN_RULES = [
    ("半导体/电子/光电", r"电子|半导体|集成电路|通信设备|智能硬件|消费电子|面板|显示|光电|仪器仪表|pcb"),
    ("汽车/零部件", r"整车制造|汽车零部件|新能源汽车|汽车"),
    ("机械/装备/自动化", r"机械|设备|电气|金属制品|重工|模具|航空|航天|工业自动化|机器人|智能装备"),
    ("新能源/电池/光伏", r"新能源|电池|光伏|储能|电力|热力|燃气|水务"),
    ("化工/新材料/建材", r"化工|化学|新材料|石化|塑料|橡胶|环保|建材|矿物|矿产"),
    ("医药/医疗器械", r"制药|医药|医疗器械|生物"),
    ("食品/快消/农牧", r"食品|饮料|酒水|餐饮|农牧|农/林/牧/渔|快速消费"),
    ("纺织/服装", r"服装|纺织|皮革"),
    ("家居/家电/轻工", r"家具|家居|家电|装饰装修|印刷|包装|造纸"),
    ("物流/贸易/供应链服务", r"货运|物流|仓储|贸易|进出口|批发|零售|电子商务|供应链"),
    ("地产/建筑", r"房地产|建筑|工程|物业"),
]
# 落到这里的多是猎头代招岗（行业写的是猎头公司自身行业）与科研/互联网，
# 本身就没有可靠的行业归属，名字写清楚比硬归类诚实。
DEFAULT_DOMAIN = "其他/未标注"


# 岗位级别：从标题提取。猎聘大量标题是纯职能名（如「生产计划/物料管理(PMC)」），
# 级别写在详情页，这里识别不了就归「未标注」（约 38%），筛选时作为可选项保留。
LEVEL_RULES = [
    ("总监/负责人", r"总监|负责人|副总|director|chief|\bhead\b"),
    ("经理", r"经理|manager"),
    ("主管", r"主管|supervisor|课长|组长|\bleader\b"),
    ("专家/资深", r"专家|资深|高级|senior|\bsr\b|principal"),
    ("专员/员", r"专员|助理|assistant|specialist|跟单|员$"),
]
DEFAULT_LEVEL = "未标注"


def map_level(title):
    for name, pat in LEVEL_RULES:
        if re.search(pat, title, re.IGNORECASE):
            return name
    return DEFAULT_LEVEL


def map_domain(raw_industry):
    """把猎聘行业词（可能是逗号分隔的复合词）归一化到领域。"""
    text = (raw_industry or "").strip()
    if not text:
        return DEFAULT_DOMAIN
    for candidate in (text.split(",")[0], text):  # 主行业优先，整串兜底
        for name, pat in DOMAIN_RULES:
            if re.search(pat, candidate, re.IGNORECASE):
                return name
    return DEFAULT_DOMAIN


def parse_card(card, city_name):
    """解析单个 job-card-pc-container 为一个岗位 dict。"""
    title_el = card.select_one(".job-title-box .ellipsis-1")
    salary_el = card.select_one(".job-salary")
    dist_el = card.select_one(".job-dq-box .ellipsis-1")
    company_el = card.select_one(".company-name")
    tags_el = card.select_one(".company-tags-box")
    link_el = card.select_one("a[data-jobId]")

    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    exp, edu = "", ""
    for tag in card.select(".labels-tag"):
        t = tag.get_text(strip=True)
        if not exp and EXP_PAT.search(t):
            exp = t
        elif not edu and EDU_PAT.search(t):
            edu = t
        if exp and edu:
            break

    job_id = link_el.get("data-jobid") if link_el else None
    link = link_el.get("href") if link_el else ""
    if link.startswith("//"):
        link = "https:" + link

    # company-tags-box 结构：[行业, 融资阶段?, 公司规模]，行业恒在第一位
    industry = ""
    if tags_el:
        parts = [t.strip() for t in tags_el.get_text(" ").split() if t.strip()]
        if parts:
            industry = parts[0]

    return {
        "title": title,
        "salary": salary_el.get_text(strip=True) if salary_el else "",
        "city": city_name,
        "district": dist_el.get_text(strip=True) if dist_el else "",
        "exp": exp,
        "edu": edu,
        "company": company_el.get_text(strip=True) if company_el else "",
        "industry": industry,
        "domain": map_domain(industry),
        "level": map_level(title),
        "link": link,
        "job_id": job_id,
    }


def cap_by_domain(items, cap):
    """按领域轮转取样，保证冷门领域（纺织/医药等）也有代表岗位。

    纯截断会让机械/电子这类大领域吃掉全部名额，领域筛选形同虚设。
    """
    buckets = collections.defaultdict(list)
    for it in items:
        buckets[it["domain"]].append(it)
    if len(items) <= cap:
        return list(items)

    order = sorted(buckets, key=lambda d: -len(buckets[d]))  # 大领域先出
    out, i = [], 0
    while len(out) < cap:
        added = False
        for d in order:
            if i < len(buckets[d]):
                out.append(buckets[d][i])
                added = True
                if len(out) >= cap:
                    break
        if not added:
            break
        i += 1
    return out


def classify(title):
    """返回 (tier, matched_keywords)。"""
    if BLOCK_PAT.search(title):
        return None, []
    if CORE_PAT.search(title):
        return "core", ["计划"]
    if RELATED_PAT.search(title):
        return "related", ["供应链"]
    return None, []


def main():
    cfg = load_config()["jobs"]
    sources = cfg.get("sources", [])

    all_items = []
    seen = set()
    errors = []

    for src in sources:
        if src.get("type") != "liepin":
            continue
        for city in src.get("cities", []):
            for career in src.get("careers", []):
                url = f"https://www.liepin.com/city-{city['slug']}/career/{career['slug']}"
                tag = f"{city['name']}/{career['label']}"
                try:
                    resp = http_get(url, timeout=40)
                    soup = BeautifulSoup(resp.content, "html.parser")
                    cards = soup.select(".job-card-pc-container")
                    got = 0
                    for card in cards:
                        item = parse_card(card, city["name"])
                        if not item:
                            continue
                        if item["job_id"] and item["job_id"] in seen:
                            continue
                        tier, matched = classify(item["title"])
                        if not tier:
                            continue
                        item["tier"] = tier
                        item["matched"] = matched
                        item["source"] = f"猎聘·{career['label']}"
                        if item["job_id"]:
                            seen.add(item["job_id"])
                        all_items.append(item)
                        got += 1
                    print(f"[ok] {tag}: {len(cards)} 卡 -> 收录 {got} 条")
                except Exception as e:
                    errors.append(f"{tag}: {e}")
                    print(f"[err] {tag}: {e}")
                time.sleep(0.8)  # 限速，避免触发猎聘反爬

    if not all_items:
        old = load_old("jobs")
        if old and old.get("items"):
            print("[warn] 全部源失败，保留旧数据")
            return 0
        save_data("jobs", {"items": [], "count": 0, "errors": errors})
        return 0

    # 排序：core 优先；同 tier 内按城市优先级
    priority = {c: i for i, c in enumerate(cfg.get("city_priority", []))}
    all_items.sort(key=lambda it: (
        0 if it["tier"] == "core" else 1,
        priority.get(it["city"], 99),
    ))

    # 每城市限流，避免岗位密集的城市（成都/上海/苏州）把其他江浙沪城市挤掉。
    # 限流按「类别 × 领域」双维度轮转：
    #   - 类别分桶（tier_caps）：core（计划）和 related（供应链）各有独立配额，
    #     否则计划岗先到先得吃满城市上限，供应链岗被挤到只剩零头；
    #   - 领域轮转（cap_by_domain）：机械/电子这类大领域会把纺织/医药全部撑掉，
    #     导致领域筛选点进去是空的。
    tier_caps = cfg.get("tier_caps", {"core": 22, "related": 15})
    per_city = {}
    for it in all_items:
        per_city.setdefault(it["city"], []).append(it)
    capped = {}
    for c, its in per_city.items():
        by_tier = collections.defaultdict(list)
        for it in its:
            by_tier[it["tier"]].append(it)
        merged = []
        for tier in ("core", "related"):
            merged.extend(cap_by_domain(by_tier.get(tier, []), tier_caps.get(tier, 30)))
        capped[c] = merged
    per_city = capped

    result = []
    for c in cfg.get("city_priority", []):
        result.extend(per_city.get(c, []))
    for c, its in per_city.items():
        if c not in cfg.get("city_priority", []):
            result.extend(its)
    all_items = result[: cfg.get("max_total", 300)]

    core_n = sum(1 for i in all_items if i["tier"] == "core")
    related_n = sum(1 for i in all_items if i["tier"] == "related")
    domains = collections.Counter(i["domain"] for i in all_items)
    levels = collections.Counter(i["level"] for i in all_items)
    print(f"[ok] 共 {len(all_items)} 条（核心 {core_n} / 相关 {related_n}）")
    print("[ok] 领域分布:", dict(domains.most_common()))
    print("[ok] 级别分布:", dict(levels.most_common()))

    save_data("jobs", {
        "items": all_items,
        "count": len(all_items),
        "core": core_n,
        "related": related_n,
        "domains": dict(domains.most_common()),
        "levels": dict(levels.most_common()),
        "errors": errors,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
