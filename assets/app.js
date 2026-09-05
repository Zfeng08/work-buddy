/* WorkBuddy 工作台前端逻辑 */
const WMO = {
  0: "晴", 1: "基本晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
  51: "小毛雨", 53: "毛雨", 55: "大毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
  66: "冻雨", 67: "冻雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
  80: "阵雨", 81: "强阵雨", 82: "暴雨", 85: "阵雪", 86: "阵雪", 95: "雷暴",
  96: "雷暴冰雹", 99: "雷暴冰雹",
};
const $ = (s) => document.querySelector(s);
const state = {
  data: {}, newsFilter: "全部", kbKeyword: "",
  jobsCity: "全部", jobsDomain: "全部", jobsLevel: "全部",
  openNoteId: null,
};
const DEFAULT_DOMAIN = "其他/未标注";
const DEFAULT_LEVEL = "未标注";

/* ---------- 图表实例管理 ----------
   切换主题时图表配色要重画，必须先 dispose 旧实例，
   否则 ECharts 会报 "instance already initialized"。 */
const charts = {};
function initChart(el) {
  if (charts[el.id]) charts[el.id].dispose();
  const c = echarts.init(el);
  charts[el.id] = c;
  return c;
}
function resizeCharts() { Object.values(charts).forEach((c) => c.resize()); }
window.addEventListener("resize", resizeCharts);

/* 从 CSS 变量取当前主题色，图表才能跟着明暗切换 */
const cssVar = (name, fallback) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
const CHART = {
  get text() { return cssVar("--text", "#e2e8f0"); },
  get dim() { return cssVar("--text-dim", "#8b93a7"); },
  get border() { return cssVar("--border", "#232a3b"); },
  get grid() { return cssVar("--bg-hover", "#1a2030"); },
  get accent() { return cssVar("--accent", "#4f8cff"); },
  get accentRGB() { return cssVar("--accent-rgb", "79,140,255"); },
  get gradB() { return cssVar("--accent-grad-b", "#7a5cff"); },
};

/* ---------- 主题切换 ---------- */
const THEME_KEY = "wb-theme";

function currentTheme() { return document.documentElement.dataset.theme; }

function syncThemeUI(t) {
  // 按钮显示的是"点一下会切到哪个"，比显示当前状态更好懂
  const next = t === "light" ? "dark" : "light";
  const icon = $("#theme-icon"), label = $("#theme-label");
  if (icon) icon.textContent = next === "light" ? "☀" : "☾";
  if (label) label.textContent = next === "light" ? "浅色" : "深色";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", t === "light" ? "#ffffff" : "#0b0e14");
}

function applyTheme(t, { persist = true, redraw = true } = {}) {
  document.documentElement.dataset.theme = t;
  if (persist) { try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* 隐私模式忽略 */ } }
  syncThemeUI(t);
  if (redraw && typeof echarts !== "undefined") {
    if (state.data.finance) renderFinanceChart();
    if (state.data.trends) renderTrendsChart();
    if (state.data.knowledge) renderGraph();
    resizeCharts();
  }
}

/* ---------- 数据加载 ---------- */
const DATASETS = ["news", "finance", "weather", "jobs", "trends", "knowledge"];

// 数据源：raw.githubusercontent.com 实时反映仓库最新提交，
// 不受 Pages 部署节奏限制（Pages 静态快照可能滞后）。
// 本地预览（localhost）或 raw 失败时回退到同源相对路径。
const RAW_BASE =
  "https://raw.githubusercontent.com/Zfeng08/work-buddy/main/data/";

async function fetchJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return await r.json();
}

async function loadJSON(name) {
  const isLocal = location.hostname === "localhost" ||
    location.hostname === "127.0.0.1";
  if (isLocal) {
    try { return await fetchJSON(`data/${name}.json`); }
    catch { return null; }
  }
  // 线上：raw 优先，相对路径兜底
  try { return await fetchJSON(RAW_BASE + name + ".json"); }
  catch {
    try { return await fetchJSON(`data/${name}.json`); }
    catch { return null; }
  }
}

// 时间戳兼容两种写法：新的带时区 ISO（2026-08-31T16:43:09+08:00）
// 和旧的无时区（2026-08-31 08:43:09，Actions 上产生的是 UTC）。
function parseTime(s) {
  if (!s) return null;
  if (s.includes("T")) return new Date(s);
  return new Date(s.replace(" ", "T") + "Z");
}

function latestFetchTime(data) {
  const times = DATASETS.map((k) => parseTime(data[k]?.fetched_at))
    .filter((t) => t && !isNaN(t))
    .sort((a, b) => b - a);
  return times[0] || null;
}

// 比较新旧数据的 fetched_at，返回发生变化的模块名
function diffDatasets(prev, next) {
  if (!prev || Object.keys(prev).length === 0) return [];
  return DATASETS.filter((k) => {
    const a = prev[k]?.fetched_at, b = next[k]?.fetched_at;
    return a && b && a !== b;
  });
}

async function loadAll(isRefresh = false) {
  const results = await Promise.all(DATASETS.map(loadJSON));
  const next = {};
  DATASETS.forEach((k, i) => { next[k] = results[i]; });

  const prev = state.data;
  state.data = next;

  const changed = isRefresh ? diffDatasets(prev, next) : DATASETS;
  const latest = latestFetchTime(next);
  if (latest) {
    $("#foot-time").textContent =
      `最近采集：${latest.toLocaleString("zh-CN", { hour12: false })}`;
  }

  // 首次加载或有模块发生变化时才重绘；纯轮询无变化则只更新时间显示，
  // 避免把用户正在看的内容（比如展开的知识库）刷没了。
  if (!isRefresh || changed.length) {
    renderAll();
  }
  updateStatusUI(changed, latest);
  return changed;
}

/* ---------- Tab 切换 ---------- */
$("#tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b === btn));
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  $(`#tab-${btn.dataset.tab}`).classList.add("active");
  window.dispatchEvent(new Event("resize")); // ECharts 自适应
});

/* ---------- 总览 ---------- */
function renderOverview() {
  const { news, jobs, knowledge, weather } = state.data;
  const stats = [
    { num: knowledge?.stats?.note_count ?? "—", label: "知识库笔记", extra: `${knowledge?.stats?.link_count ?? 0} 条关联` },
    { num: knowledge?.stats?.tag_count ?? "—", label: "标签", extra: "自动索引" },
    { num: news?.count ?? "—", label: "资讯条目", extra: `${news?.sources_ok ?? 0} 个源在线` },
    { num: jobs?.core ?? jobs?.items?.filter((j) => j.tier === "core").length ?? "—", label: "计划岗(核心)", extra: "生产计划/物料/PMC" },
    { num: jobs?.related ?? jobs?.items?.filter((j) => j.tier === "related").length ?? "—", label: "供应链岗", extra: "采购/物流/仓储" },
    { num: weather?.cities?.length ?? "—", label: "关注城市", extra: (weather?.cities || []).map((c) => c.name).join(" · ") },
  ];
  $("#stat-grid").innerHTML = stats.map((s) => `
    <div class="stat"><div class="num">${s.num}</div><div class="label">${s.label}</div>
    <div class="extra">${s.extra || ""}</div></div>`).join("");

  // 重点岗位：核心计划岗优先
  const hot = (jobs?.items || []).filter((j) => j.tier === "core").slice(0, 6);
  $("#ov-jobs").innerHTML = hot.length ? hot.map(listItemJob).join("")
    : `<li class="empty">暂无计划岗数据</li>`;

  // 天气速览
  $("#ov-weather").innerHTML = (weather?.cities || []).map((c) => `
    <div class="mini-city">
      <div class="city">${c.name}</div>
      <div class="temp">${Math.round(c.current.temperature)}°</div>
      <div class="desc">${WMO[c.current.weather_code] || "—"} · PM2.5 ${c.current.pm25 ?? "—"}</div>
    </div>`).join("") || `<div class="empty">暂无天气数据</div>`;

  // 最新资讯
  const items = (news?.items || []).slice(0, 8);
  $("#ov-news").innerHTML = items.length ? items.map(listItemNews).join("")
    : `<li class="empty">暂无资讯数据，等待 Actions 首次运行</li>`;
}

/* ---------- 资讯 ---------- */
function renderNews() {
  const news = state.data.news;
  const items = news?.items || [];
  const cats = ["全部", ...new Set(items.map((i) => i.category).filter(Boolean))];
  $("#news-filter").innerHTML = cats.map((c) =>
    `<button class="${c === state.newsFilter ? "active" : ""}" data-cat="${c}">${c}</button>`).join("");
  $("#news-filter").querySelectorAll("button").forEach((b) =>
    b.onclick = () => { state.newsFilter = b.dataset.cat; renderNews(); });

  const filtered = state.newsFilter === "全部" ? items : items.filter((i) => i.category === state.newsFilter);
  $("#news-meta").textContent = `${filtered.length} 条 · 采集于 ${news?.fetched_at ?? "—"}`;
  $("#news-list").innerHTML = filtered.length ? filtered.map(listItemNews).join("")
    : `<li class="empty">暂无数据</li>`;
}
function listItemNews(i) {
  return `<li><a href="${i.link}" target="_blank" rel="noopener">${esc(i.title)}</a>
    <div class="meta"><span class="source-chip">${esc(i.source)}</span>
    ${i.category ? `<span class="tag">${esc(i.category)}</span>` : ""}
    <span>${esc((i.published || "").slice(0, 16))}</span></div></li>`;
}

/* ---------- 行情 ---------- */
function renderFinance() {
  const fin = state.data.finance;
  $("#quote-grid").innerHTML = (fin?.quotes || []).map((q) => {
    const cls = q.change_pct >= 0 ? "up" : "down";
    const sign = q.change_pct >= 0 ? "+" : "";
    return `<div class="quote"><div class="name">${esc(q.name)}</div>
      <div class="price">${q.price.toLocaleString()}</div>
      <div class="chg ${cls}">${sign}${q.change} (${sign}${q.change_pct}%)</div></div>`;
  }).join("") || `<div class="empty">暂无行情数据</div>`;
  renderFinanceChart();
}
function renderFinanceChart() {
  const el = $("#finance-chart");
  const hist = state.data.finance?.history || [];
  const series = hist.map((h) => {
    const sh = h.quotes.find((q) => q.name === "上证指数");
    return sh ? [h.date, sh.price] : null;
  }).filter(Boolean);
  if (!series.length) { el.innerHTML = `<div class="empty">暂无历史数据（每日采集自动积累）</div>`; return; }
  const chart = initChart(el);
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    grid: { left: 60, right: 20, top: 20, bottom: 30 },
    xAxis: { type: "time", axisLine: { lineStyle: { color: CHART.border } }, axisLabel: { color: CHART.dim } },
    yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: CHART.grid } }, axisLabel: { color: CHART.dim } },
    series: [{
      type: "line", data: series, smooth: true, symbol: "none",
      lineStyle: { color: CHART.accent, width: 2 },
      areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: `rgba(${CHART.accentRGB},0.25)` }, { offset: 1, color: `rgba(${CHART.accentRGB},0)` }] } },
    }],
  });
}

/* ---------- 天气 ---------- */
function renderWeather() {
  $("#weather-grid").innerHTML = (state.data.weather?.cities || []).map((c) => {
    const cur = c.current;
    const pm = cur.pm25;
    const aqiText = pm == null ? "PM2.5 暂无" :
      pm <= 35 ? `优 ${pm}` : pm <= 75 ? `良 ${pm}` : `污染 ${pm}`;
    const daily = c.daily.map((d) => `
      <div class="wd"><div class="d">${d.date.slice(5)}</div>
      <div>${WMO[d.weather_code] || "—"}</div>
      <div class="t">${Math.round(d.temp_min)}° / ${Math.round(d.temp_max)}°</div>
      <div>💧${d.precip_prob ?? 0}%</div></div>`).join("");
    return `<div class="card weather-city">
      <div class="city">${c.name} <span class="note">${esc(c.note)}</span></div>
      <div class="temp">${Math.round(cur.temperature)}°C</div>
      <div class="desc">体感 ${Math.round(cur.apparent)}° · ${WMO[cur.weather_code] || "—"} · 湿度 ${cur.humidity}% · 风 ${cur.wind_speed}km/h</div>
      <div class="aqi tag ${pm != null && pm > 75 ? "" : "hit"}">PM2.5 ${aqiText}</div>
      <div class="weather-daily">${daily}</div></div>`;
  }).join("") || `<div class="card"><div class="empty">暂无天气数据</div></div>`;
}

/* ---------- 岗位 ---------- */
function renderJobs() {
  const jobs = state.data.jobs;
  const items = jobs?.items || [];
  const cities = ["全部", ...new Set(items.map((j) => j.city))];
  $("#jobs-meta").textContent =
    `${jobs?.count ?? 0} 条 · 核心 ${jobs?.core ?? "—"} · 采集于 ${jobs?.fetched_at ?? "—"}`;

  // 城市筛选
  bindChipRow($("#jobs-filter"), cities, state.jobsCity, (v) => {
    state.jobsCity = v; renderJobs();
  });

  // 先按城市过滤，领域/级别按钮的计数要跟着上层筛选走，否则对不上
  const byCity = state.jobsCity === "全部" ? items : items.filter((j) => j.city === state.jobsCity);

  const dCount = countBy(byCity, (j) => j.domain || DEFAULT_DOMAIN);
  const domains = Object.keys(dCount).sort((a, b) => dCount[b] - dCount[a]);
  fallbackFilter("jobsDomain", dCount);
  bindChipRow($("#jobs-domain-filter"), ["全部", ...domains], state.jobsDomain,
    (v) => { state.jobsDomain = v; renderJobs(); },
    (d) => (d === "全部" ? `全部 ${byCity.length}` : `${d} ${dCount[d]}`));

  // 级别筛选（猎聘约 38% 标题不带级别，识别不出的归「未标注」，可单独筛出来看）
  const byDomain = state.jobsDomain === "全部"
    ? byCity
    : byCity.filter((j) => (j.domain || DEFAULT_DOMAIN) === state.jobsDomain);
  const lCount = countBy(byDomain, (j) => j.level || DEFAULT_LEVEL);
  const levels = Object.keys(lCount).sort((a, b) => lCount[b] - lCount[a]);
  fallbackFilter("jobsLevel", lCount);
  bindChipRow($("#jobs-level-filter"), ["全部", ...levels], state.jobsLevel,
    (v) => { state.jobsLevel = v; renderJobs(); },
    (l) => (l === "全部" ? `全部 ${byDomain.length}` : `${l} ${lCount[l]}`));

  const filtered = state.jobsLevel === "全部"
    ? byDomain
    : byDomain.filter((j) => (j.level || DEFAULT_LEVEL) === state.jobsLevel);
  $("#jobs-list").innerHTML = filtered.map(listItemJob).join("")
    || `<li class="empty">当前筛选条件下没有岗位</li>`;
}

/** 上层筛选变化后，若当前选中的下层筛选项已无岗位，自动回落到「全部」。 */
function fallbackFilter(key, counts) {
  if (state[key] !== "全部" && !counts[state[key]]) state[key] = "全部";
}

function countBy(arr, pick) {
  const c = {};
  for (const x of arr) {
    const k = pick(x);
    c[k] = (c[k] || 0) + 1;
  }
  return c;
}

/** 渲染一行筛选按钮。active 为当前选中值，onPick 接收按钮值。 */
function bindChipRow(el, values, active, onPick, label) {
  if (!el) return;
  el.innerHTML = values.map((v) =>
    `<button class="${v === active ? "active" : ""}" data-val="${esc(v)}">${esc(label ? label(v) : v)}</button>`
  ).join("");
  el.querySelectorAll("button").forEach((b) => {
    b.onclick = () => onPick(b.dataset.val);
  });
}

function listItemJob(j) {
  const tierTag = j.tier === "core"
    ? `<span class="tag hit">计划</span>`
    : `<span class="tag">供应链</span>`;
  const meta = [j.salary, j.exp, j.edu, j.district].filter(Boolean).join(" · ");
  return `<li><a href="${j.link}" target="_blank" rel="noopener">${esc(j.title)}</a>
    <div class="meta"><span class="source-chip">${esc(j.city)}</span>${tierTag}
    <span class="tag domain">${esc(j.domain || DEFAULT_DOMAIN)}</span>
    ${j.level && j.level !== DEFAULT_LEVEL ? `<span class="tag level">${esc(j.level)}</span>` : ""}
    <span>${esc(j.company)}</span></div>
    <div class="meta" style="margin-top:2px">${esc(meta)}</div></li>`;
}

/* ---------- 趋势 ---------- */
function renderTrends() {
  const repos = state.data.trends?.repos || [];
  $("#trends-list").innerHTML = repos.map((r) => `
    <li><a href="${r.url}" target="_blank" rel="noopener">${esc(r.full_name)}</a>
    <div class="meta"><span class="tag">${esc(r.language)}</span>
    <span>★ ${r.stars.toLocaleString()}</span><span>今日 +${r.stars_today}</span></div>
    <div class="meta" style="margin-top:2px">${esc(r.description || "")}</div></li>`).join("")
    || `<li class="empty">暂无数据</li>`;
  renderTrendsChart();
}
function renderTrendsChart() {
  const el = $("#trends-chart");
  const repos = (state.data.trends?.repos || []).slice(0, 12);
  if (!repos.length) { el.innerHTML = `<div class="empty">暂无数据</div>`; return; }
  const chart = initChart(el);
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: 220, right: 40, top: 10, bottom: 30 },
    xAxis: { type: "value", axisLabel: { color: CHART.dim }, splitLine: { lineStyle: { color: CHART.grid } } },
    yAxis: { type: "category", data: repos.map((r) => r.full_name).reverse(),
      axisLabel: { color: CHART.text, fontSize: 11 } },
    series: [{ type: "bar", data: repos.map((r) => r.stars_today).reverse(),
      itemStyle: { color: { type: "linear", x: 0, y: 0, x2: 1, y2: 0,
        colorStops: [{ offset: 0, color: CHART.accent }, { offset: 1, color: CHART.gradB }] },
        borderRadius: [0, 6, 6, 0] }, barWidth: 14 }],
  });
}

/* ---------- 知识库 ---------- */
function renderKnowledge() {
  const kb = state.data.knowledge;
  if (!kb) { $("#kb-notes").innerHTML = `<div class="empty">知识库尚未构建</div>`; return; }
  hideKwPopover();

  // 关键词云：按「覆盖文章数」上色，按总频次控字号
  const kwi = kb.keyword_index || {};
  const kws = Object.entries(kwi);
  const maxDocs = Math.max(1, ...kws.map(([, v]) => v.length));
  $("#kb-kw-count").textContent = kws.length;
  $("#kw-cloud").innerHTML = kws.length ? kws
    .sort((a, b) => (b[1].length - a[1].length) || (sumCounts(b[1]) - sumCounts(a[1])))
    .map(([k, ids]) => {
      const cls = ids.length >= maxDocs * 0.6 ? "lg" : ids.length >= maxDocs * 0.3 ? "md" : "sm";
      return `<span class="kw-chip ${cls}" data-kw="${esc(k)}">${esc(k)} <span style="opacity:.55">${ids.length}</span></span>`;
    }).join("") : `<div class="empty">暂无关键词</div>`;
  $("#kw-cloud").querySelectorAll(".kw-chip").forEach((el) =>
    el.onclick = (e) => openKwPopover(el.dataset.kw, e.currentTarget));

  // 标签云（沿用旧行为）
  const tagIndex = kb.tag_index || {};
  $("#tag-cloud").innerHTML = Object.entries(tagIndex).sort((a, b) => b[1].length - a[1].length)
    .map(([t, ids]) => `<span class="tag" data-tag="${esc(t)}">${esc(t)} (${ids.length})</span>`).join("");
  $("#tag-cloud").querySelectorAll(".tag").forEach((el) =>
    el.onclick = () => { $("#kb-search").value = el.dataset.tag; state.kbKeyword = el.dataset.tag; renderKnowledge(); });

  $("#kb-stats").innerHTML = `
    <div><span>笔记总数</span><span>${kb.stats.note_count}</span></div>
    <div><span>关键词</span><span>${kws.length}</span></div>
    <div><span>标签</span><span>${kb.stats.tag_count}</span></div>
    <div><span>关联条数</span><span>${kb.stats.link_count}</span></div>
    <div><span>平均关联度</span><span>${avgDegree(kb)}</span></div>`;

  const kw = state.kbKeyword.toLowerCase();
  const notes = (kb.notes || []).filter((n) =>
    !kw || n.title.toLowerCase().includes(kw) || n.tags.join(" ").toLowerCase().includes(kw)
    || (n.keywords || []).join(" ").toLowerCase().includes(kw)
    || n.summary.toLowerCase().includes(kw));
  const byId = Object.fromEntries((kb.notes || []).map((n) => [n.id, n]));

  $("#kb-notes").innerHTML = notes.length ? notes.map((n) => {
    const isOpen = state.openNoteId === n.id;
    const kwPills = (n.keywords || []).slice(0, 12).map((k) =>
      `<span class="kw-pill" data-kw="${esc(k)}">${esc(k)}</span>`).join("");
    const rel = (kb.related?.[n.id] || []).map((r) => {
      const target = byId[r.id];
      return target ? `<div class="rel-item"><span class="score">${r.score}</span>
        <span>${esc(target.title)}</span>
        <span class="reason">${esc(r.reasons.join(" · "))}</span></div>` : "";
    }).join("");
    return `<div class="note-card ${isOpen ? "open" : ""}" data-id="${esc(n.id)}">
      <h3 data-toggle><span class="chev">▶</span>${esc(n.title)}</h3>
      <div class="meta-row">
        ${n.date ? `<span>${esc(n.date)}</span>` : ""}
        <span>${n.word_count} 字</span>
        ${n.source ? `<span class="source-chip">来源：${esc(truncate(n.source, 32))}</span>` : ""}
      </div>
      <div class="tags">
        ${n.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}
        ${kwPills ? `<span style="font-size:11px;color:var(--text-dim);margin-left:4px">关键词</span>${kwPills}` : ""}
      </div>
      ${isOpen ? `
        <div class="body">${n.body_html || `<p>${esc(n.summary)}…</p>`}
          ${n.source ? `<a class="source-link" href="${esc(n.source)}" target="_blank" rel="noopener">原文链接 ↗</a>` : ""}
        </div>
        ${rel ? `<div class="rel-box"><h4>相关笔记</h4>${rel}</div>` : ""}
      ` : `<div class="summary">${esc(n.summary)}…</div>`}
    </div>`;
  }).join("") : `<div class="empty">没有匹配的笔记</div>`;

  // 展开/折叠
  $("#kb-notes").querySelectorAll("[data-toggle]").forEach((el) =>
    el.onclick = () => {
      const card = el.closest(".note-card");
      const id = card.dataset.id;
      state.openNoteId = state.openNoteId === id ? null : id;
      renderKnowledge();
      // 展开后滚到视野内
      if (state.openNoteId === id) {
        card.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  // 正文里的关键词链接 / 头部关键词 pill → 弹层
  $("#kb-notes").querySelectorAll("[data-kw]").forEach((el) =>
    el.onclick = (e) => { e.stopPropagation(); openKwPopover(el.dataset.kw, el); });
}
function sumCounts(arr) { return arr.reduce((s, x) => s + (x.count || 0), 0); }
function avgDegree(kb) {
  const n = kb.stats.note_count || 1;
  return (kb.stats.link_count * 2 / n).toFixed(1);
}
function truncate(s, n) { return s.length > n ? s.slice(0, n) + "…" : s; }
function openKwPopover(kw, anchor) {
  const kwi = state.data.knowledge?.keyword_index || {};
  const ids = kwi[kw];
  if (!ids) return;
  const byId = Object.fromEntries((state.data.knowledge.notes || []).map((n) => [n.id, n]));
  const pop = $("#kw-popover");
  pop.innerHTML = `
    <div class="pop-title">包含关键词的笔记（${ids.length}）</div>
    <div class="pop-kw">${esc(kw)}</div>
    <div class="pop-list">
      ${ids.map((it) => {
        const n = byId[it.note_id];
        return n ? `<a href="#" data-jump="${esc(n.id)}"><span>${esc(n.title)}</span><span class="ct">${it.count} 次</span></a>` : "";
      }).join("") || `<div class="pop-empty">无</div>`}
    </div>`;
  pop.hidden = false;
  // 定位：默认放在 anchor 下方，超出底部就放到上方
  const r = anchor.getBoundingClientRect();
  const popR = pop.getBoundingClientRect();
  let top = r.bottom + 8;
  if (top + popR.height > window.innerHeight - 12) top = Math.max(12, r.top - popR.height - 8);
  let left = Math.min(window.innerWidth - popR.width - 12, r.left);
  pop.style.top = top + "px";
  pop.style.left = left + "px";
  // 点击弹层里某条笔记 → 打开它
  pop.querySelectorAll("[data-jump]").forEach((el) =>
    el.onclick = (e) => {
      e.preventDefault();
      state.openNoteId = el.dataset.jump;
      hideKwPopover();
      renderKnowledge();
      // 等渲染完再滚
      requestAnimationFrame(() => {
        const card = document.querySelector(`.note-card[data-id="${CSS.escape(state.openNoteId)}"]`);
        card?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
}
function hideKwPopover() {
  const pop = $("#kw-popover");
  if (pop) pop.hidden = true;
}
document.addEventListener("click", (e) => {
  const pop = $("#kw-popover");
  if (!pop || pop.hidden) return;
  if (!pop.contains(e.target) && !e.target.closest("[data-kw]")) hideKwPopover();
});

/* ---------- 图谱 ---------- */
function renderGraph() {
  const el = $("#graph-chart");
  const g = state.data.knowledge?.graph;
  if (!g || !g.nodes.length) { el.innerHTML = `<div class="empty">暂无图谱数据</div>`; return; }
  const cats = [...new Set(g.nodes.map((n) => n.category))].map((name) => ({ name }));
  // 浅色底上原配色偏淡，换一组更深的
  const palette = currentTheme() === "light"
    ? ["#2f6bff", "#0f9d76", "#e08c1a", "#6a4bf5", "#d93b40", "#1d9fb8"]
    : ["#4f8cff", "#22c993", "#f5a623", "#7a5cff", "#f0565b", "#35c1d6"];
  const chart = initChart(el);
  chart.setOption({
    backgroundColor: "transparent",
    tooltip: { formatter: (p) => p.dataType === "node" ? p.data.name : "" },
    legend: [{ data: cats.map((c) => c.name), textStyle: { color: CHART.dim }, bottom: 10 }],
    series: [{
      type: "graph", layout: "force", roam: true, draggable: true,
      categories: cats, color: palette,
      force: { repulsion: 320, edgeLength: [80, 180], gravity: 0.08 },
      label: { show: true, color: CHART.text, fontSize: 12, position: "right" },
      edgeLabel: { show: false },
      lineStyle: { color: "source", curveness: 0.15, opacity: 0.7 },
      emphasis: { focus: "adjacency", lineStyle: { width: 4 } },
      data: g.nodes, links: g.links,
    }],
  });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderAll() {
  renderOverview(); renderNews(); renderFinance(); renderWeather();
  renderJobs(); renderTrends(); renderKnowledge(); renderGraph();
}

/* ---------- 自动刷新 ---------- */
const REFRESH_INTERVAL = 60;   // 秒
let autoRefresh = true;
let secondsLeft = REFRESH_INTERVAL;
let tickTimer = null;
let refreshing = false;

function formatAge(date) {
  const mins = Math.floor((Date.now() - date.getTime()) / 60000);
  if (mins < 1) return "刚刚更新";
  if (mins < 60) return `${mins} 分钟前更新`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} 小时前更新`;
  return `${Math.floor(hrs / 24)} 天前更新`;
}

function updateStatusUI(changed, latest) {
  const ageEl = $("#data-age");
  const dot = $("#live-dot");

  if (latest) {
    ageEl.textContent = formatAge(latest);
    // 数据超过 2 小时没更新，说明定时任务可能出问题了，标黄警示
    const stale = Date.now() - latest.getTime() > 2 * 3600 * 1000;
    ageEl.style.color = stale ? cssVar("--warn", "#f5a623") : "";
  } else {
    ageEl.textContent = "暂无数据";
  }

  if (autoRefresh) {
    dot.classList.remove("paused");
  } else {
    dot.classList.add("paused");
  }

  // 有模块更新时闪一下，让用户知道数据刷新过了
  if (changed && changed.length) {
    dot.classList.remove("updated");
    void dot.offsetWidth;   // 强制重排，让动画能重复触发
    dot.classList.add("updated");
  }
}

async function doRefresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    await loadAll(true);
  } catch (e) {
    console.warn("刷新失败", e);
  } finally {
    refreshing = false;
    secondsLeft = REFRESH_INTERVAL;
  }
}

function startTicker() {
  clearInterval(tickTimer);
  tickTimer = setInterval(() => {
    // 页面切到后台就不刷，省电省流量（手机端尤其重要）
    if (document.hidden) return;
    secondsLeft--;
    $("#countdown").textContent = `${secondsLeft}s`;
    if (secondsLeft <= 0) doRefresh();
  }, 1000);
}

function setAutoRefresh(on) {
  autoRefresh = on;
  const btn = $("#refresh-toggle");
  btn.textContent = on ? `自动刷新 ${REFRESH_INTERVAL}s` : "已暂停";
  btn.classList.toggle("off", !on);
  if (on) {
    secondsLeft = REFRESH_INTERVAL;
    startTicker();
    doRefresh();
  } else {
    clearInterval(tickTimer);
    $("#countdown").textContent = "--";
  }
  updateStatusUI([], latestFetchTime(state.data));
}

$("#refresh-toggle").addEventListener("click", () => setAutoRefresh(!autoRefresh));

// 主题切换
$("#theme-toggle").addEventListener("click", () => {
  applyTheme(currentTheme() === "light" ? "dark" : "light");
});

// 用户没手动选过时，跟着系统深浅色走
try {
  window.matchMedia("(prefers-color-scheme: light)")
    .addEventListener("change", (e) => {
      if (!localStorage.getItem(THEME_KEY)) applyTheme(e.matches ? "light" : "dark", { persist: false });
    });
} catch (e) { /* 老浏览器忽略 */ }

// 手机/电脑切回页面时立刻拉一次最新数据，不用等倒计时
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && autoRefresh) doRefresh();
});

$("#kb-search").addEventListener("input", (e) => { state.kbKeyword = e.target.value; renderKnowledge(); });

(async function init() {
  syncThemeUI(currentTheme());   // 让按钮文案匹配 head 里定好的主题
  await loadAll();
  setAutoRefresh(true);
})();
