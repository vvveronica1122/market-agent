/* Market Agent -- front end.

   Two things worth noticing if you're reading this to learn:

   1. Everything derived from API data is inserted with textContent / DOM
      nodes, never innerHTML string concatenation. News headlines come from
      a third party; treating them as trusted markup is how you get XSS.

   2. The chart is drawn with plain canvas -- no chart library, so the page
      has no external dependency and works offline. */

const COLORS = {
  series: "#2a78d6",
  seriesFill: "rgba(42, 120, 214, 0.10)",
  seriesBar: "#86b6ef",
  up: "#0F7B36",
  down: "#B3261E",
  gridline: "#EEDFD8",
  axis: "#D6C3BC",
  muted: "#8A7278",
  surface: "#FFFBF9",
};

const state = {
  view: "home",
  themes: [],        // theme setup from /api/themes (names, benchmarks, companies)
  chart: null,
  chat: [],
  chatBusy: false,
  renderToken: 0,
  market: null,       // session state from /api/overview
  lastSession: null,  // date of the session the latest prices come from
  sessionToday: null, // today's date in New York
};

// Set by demo-config.js in the static demo (demo/build.py); absent when the
// app runs against its own server.
const DEMO = window.MARKET_AGENT_DEMO || null;

const viewEl = document.getElementById("view");
const stripEl = document.getElementById("market-strip");
const tooltipEl = document.getElementById("tooltip");
const toastEl = document.getElementById("toast");

/* ---------------- routing ----------------

   Every page has its own address (#/theme/ai-compute, #/stock/MU), so the
   browser's back button works and any page can be linked to directly. */

const ROUTES = [
  [/^#\/?$/, () => showHome()],
  [/^#\/theme\/([^/]+)(?:\/([a-z]+))?$/, (m) => showTheme(decodeURIComponent(m[1]), m[2])],
  [/^#\/stock\/([^/]+)(?:\/([a-z]+))?$/, (m) => showDetail(decodeURIComponent(m[1]).toUpperCase(), m[2])],
  [/^#\/earnings$/, () => showEarnings()],
  [/^#\/discover$/, () => showDiscover()],
  [/^#\/ask$/, () => showChat()],
  [/^#\/search\/([^/]+)$/, (m) => showSearch(decodeURIComponent(m[1]).toUpperCase())],
];

function route() {
  hideTooltip();
  closeThemeMenu();
  const hash = location.hash || "#/";
  for (const [pattern, handler] of ROUTES) {
    const match = hash.match(pattern);
    if (match) return handler(match);
  }
  showHome();
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

const stockHash = (ticker) => "#/stock/" + encodeURIComponent(ticker);
const themeHash = (id) => "#/theme/" + encodeURIComponent(id);

// Each view awaits the network. If the reader clicks elsewhere meanwhile,
// the slow response must not paint over the page they moved to -- so every
// view takes a token and checks it is still current before rendering.
function beginView(view, navKey) {
  state.view = view;
  setActiveNav(navKey === undefined ? view : navKey);
  return ++state.renderToken;
}

const isCurrent = (token) => token === state.renderToken;

async function api(method, url, body) {
  if (DEMO) return demoApi(method, url);
  try {
    const res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
  } catch (err) {
    return { ok: false, data: { error: String(err) } };
  }
}

// The static demo has no server: each request maps to a JSON file captured
// from the live app once (demo/build.py), and nothing can be changed.
async function demoApi(method, url) {
  if (method !== "GET") {
    return { ok: false, data: { error: "The demo is read-only. Run Market Agent locally to edit themes." } };
  }
  const [path, query] = url.replace(/^\/api\//, "").split("?");
  let file = `data/${path}.json`;
  if (path === "search") {
    const q = (new URLSearchParams(query || "").get("q") || "").toUpperCase();
    file = `data/search/${encodeURIComponent(q)}.json`;
    const found = await fetch(file).catch(() => null);
    if (!found || !found.ok) {
      return { ok: true, data: { results: [], message: `${q} isn't in this snapshot. The demo covers the ` +
        "companies in its themes and on its Discover page." } };
    }
    return { ok: true, data: await found.json() };
  }
  try {
    const res = await fetch(file);
    if (!res.ok) return { ok: false, data: { error: "Not in this snapshot." } };
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, data: { error: "Not in this snapshot." } };
  }
}

function buildDemoBanner() {
  const banner = el("div", "demo-banner");
  banner.setAttribute("role", "note");
  banner.appendChild(el("strong", null, "Demo. "));
  banner.appendChild(document.createTextNode(
    `A snapshot of the ${DEMO.snapshot_session ? formatSession(DEMO.snapshot_session) : "captured"} session, ` +
    `taken ${DEMO.captured_label || ""}. Prices don't update, the AI text was written when the snapshot was ` +
    "taken, and Ask replays recorded conversations. Nothing here is financial advice."));
  if (DEMO.repo_url) {
    banner.appendChild(document.createTextNode(" "));
    const link = el("a", null, "How it's built ↗");
    link.href = DEMO.repo_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    banner.appendChild(link);
  }
  return banner;
}

function toast(message) {
  toastEl.textContent = message;
  toastEl.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { toastEl.hidden = true; }, 3200);
}

/* ---------------- theme vocabulary ---------------- */

// How a move lines up with its peers. The rule lives in tools/relative.py;
// these are the words the page uses for it.
const ATTRIBUTION = {
  theme: { label: "With theme", note: "Tracked its peers: the gap to the typical peer is small next to the move." },
  mixed: { label: "Partly shared", note: "Partly tracked its peers: the gap to the typical peer is 40-60% of the move." },
  company: { label: "Own move", note: "Diverged from its peers: it moved alone, against them, or held up while they fell." },
  quiet: { label: "Quiet", note: "Neither it nor its peers moved as much as 1% today." },
};

function attributionTag(attr) {
  const info = ATTRIBUTION[attr];
  const tag = el("span", "attr-tag " + (info ? "attr-" + attr : "attr-none"),
                 info ? info.label : "No peer data");
  tag.title = info ? info.note : "Fewer than two peers with a price today, so there's nothing to compare with.";
  return tag;
}

function pts(value) {
  if (value === null || value === undefined) return "--";
  return (value >= 0 ? "+" : "") + Number(value).toFixed(2) + "pt";
}

/* ---------------- which session ----------------

   Outside market hours the latest prices are a past session's. On a Monday
   morning, "down 10% today" would be Friday's move; the page says which
   session it is instead. */

function sessionIsToday() {
  return !state.lastSession || !state.sessionToday || state.lastSession === state.sessionToday;
}

function formatSession(iso) {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(LOCALE, { weekday: "short", month: "short", day: "numeric" });
}

// "today" or "on Fri, Oct 2" -- for sentences.
function sessionPhrase() {
  return sessionIsToday() ? "today" : "on " + formatSession(state.lastSession);
}

// "today" or "Fri, Oct 2" -- for labels.
function sessionShort() {
  return sessionIsToday() ? "today" : formatSession(state.lastSession);
}

function sessionNote() {
  if (sessionIsToday() && !DEMO) return null;
  if (DEMO) return el("p", "session-note", `Prices and moves are from the ${formatSession(state.lastSession)} session.`);
  const now = state.market ? ` -- the US market is ${state.market.state} now` : "";
  return el("p", "session-note",
    `Prices and moves are from the ${formatSession(state.lastSession)} session${now}.`);
}

/* ---------------- attention score, explained ---------------- */

function attentionTitle(att) {
  if (!att || !att.parts) return "";
  const p = att.parts;
  return `Attention score ${num(att.score, 0)} = size of move ${num(p.move, 0)} (8 a point, up to 45)` +
    ` + gap vs ${att.reference === "peers" ? "peers" : "the market"} ${num(p.relative, 0)} (12 if 1.5pt or more)` +
    ` + earnings ${num(p.earnings, 0)} (25 within a week, 12 within two)` +
    ` + news ${num(p.news, 0)} (3 a headline, up to 12). 45 or more needs attention; 20 or more is worth a look.`;
}

function setTitle(name) {
  document.title = name ? `${name} · Market Agent` : "Market Agent";
}

/* ---------------- helpers ---------------- */

// The page is written in English, so dates and numbers are too, whatever
// language the browser runs in -- otherwise "Oct 15" sits beside
// "2026年10月15日" on the same screen.
const LOCALE = "en-US";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function money(value) {
  if (value === null || value === undefined) return "--";
  return "$" + Number(value).toFixed(2);
}

function pct(value) {
  if (value === null || value === undefined) return "--";
  return (value >= 0 ? "+" : "") + Number(value).toFixed(2) + "%";
}

function toneClass(value) {
  if (value === null || value === undefined) return "";
  return value >= 0 ? "up-text" : "down-text";
}

function formatLongDate(iso) {
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString(LOCALE, { month: "short", day: "numeric", year: "numeric" });
}

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(LOCALE, { month: "short", day: "numeric" });
}

function setActiveNav(key) {
  document.querySelectorAll(".nav-item[data-route]").forEach((item) => {
    const active = item.dataset.route === key;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
}

/* ---------------- theme setup + sidebar ---------------- */

async function loadThemes() {
  const { ok, data } = await api("GET", "/api/themes");
  if (ok) {
    state.themes = data.themes || [];
    state.limits = data.limits || {};
  }
  renderNavThemes();
}

function renderNavThemes() {
  const wrap = document.getElementById("nav-themes");
  wrap.replaceChildren();
  state.themes.forEach((t) => {
    const link = el("a", "nav-item nav-theme");
    link.href = themeHash(t.id);
    link.dataset.route = "theme:" + t.id;
    link.appendChild(el("span", null, t.name));
    link.appendChild(el("span", "nav-count", t.stocks.length));
    wrap.appendChild(link);
  });
  // Re-apply the highlight: the links were just rebuilt.
  const current = state.view === "theme" ? "theme:" + state.themeId : state.view;
  setActiveNav(current);
}

/* ---------------- market strip ---------------- */

async function loadOverview() {
  try {
    const { ok, data } = await api("GET", "/api/overview");
    if (!ok) throw new Error(data.error || "overview unavailable");
    state.market = data.market || null;
    state.lastSession = data.last_session || null;
    state.sessionToday = data.today || null;
    renderStrip(data);
  } catch (err) {
    stripEl.replaceChildren(el("div", "strip-loading", "Market data unavailable"));
  }
}

function renderStrip(data) {
  const frag = document.createDocumentFragment();

  (data.indices || []).forEach((idx) => {
    const wrap = el("div", "index");
    wrap.appendChild(el("span", "label", idx.label));
    if (idx.error) {
      wrap.appendChild(el("span", "value", "--"));
    } else {
      wrap.appendChild(el("span", "value", money(idx.price)));
      wrap.appendChild(el("span", "delta " + toneClass(idx.change_percent), pct(idx.change_percent)));
    }
    frag.appendChild(wrap);
  });

  const session = el("div", "session");
  const dot = el("span", "dot");
  if (data.market && data.market.state === "open") dot.classList.add("open");
  session.appendChild(dot);
  session.appendChild(el("span", null, DEMO
    ? `snapshot · ${data.last_session ? formatSession(data.last_session) : ""}`
    : data.market ? `${data.market.state} · ${data.market.time}` : ""));
  frag.appendChild(session);

  stripEl.replaceChildren(frag);
}

/* ---------------- home ----------------

   The first layer: what needs looking at today. One card per theme --
   how the theme did against its benchmark, how widely, and the few
   companies that most need attention. Everything else is a click away on
   the theme's own page. */

const BENCHMARK_SUGGESTIONS = [
  ["SPY", "S&P 500"], ["QQQ", "Nasdaq-100"], ["SMH", "Semiconductors"], ["SOXX", "Semiconductors"],
  ["XLK", "Technology"], ["XLU", "Utilities"], ["XLI", "Industrials"], ["XLF", "Financials"],
  ["XLE", "Energy"], ["XLV", "Health care"], ["ITA", "Aerospace & defense"], ["IWM", "Small caps"],
];

async function showHome() {
  const token = beginView("home");
  setTitle("Home");
  viewEl.replaceChildren(el("p", "loading-text", "Loading your themes..."));

  const { ok, data } = await api("GET", "/api/home");
  if (!isCurrent(token)) return;
  if (!ok) {
    viewEl.replaceChildren(el("p", "empty", "Could not load your themes: " + (data.error || "")));
    return;
  }

  const frag = document.createDocumentFragment();
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, "Home"));
  frag.appendChild(head);
  frag.appendChild(el("p", "view-sub",
    "Each theme measured against its benchmark ETF and against its own peers. " +
    "Within a theme, companies are ordered by what needs attention today."));
  const note = sessionNote();
  if (note) frag.appendChild(note);

  const blocks = data.themes || [];
  if (!blocks.length || blocks.every((b) => !b.rows.length)) {
    frag.appendChild(el("p", "empty", "No companies yet. Create a theme below and add some."));
  } else {
    // The brief loads separately so a slow model call never delays the
    // numbers -- they're the urgent part.
    const briefPanel = buildBriefPanel();
    frag.appendChild(briefPanel);
    setTimeout(() => loadBrief(briefPanel, false), 0);
  }

  const grid = el("div", "tblock-grid");
  blocks.forEach((block) => grid.appendChild(buildThemeBlock(block)));
  frag.appendChild(grid);

  frag.appendChild(buildReadingGuide());
  if (!DEMO) frag.appendChild(buildNewThemeForm());
  viewEl.replaceChildren(frag);
}

function buildReadingGuide() {
  const guide = el("details", "reading-guide");
  guide.appendChild(el("summary", null, "How to read the theme cards"));
  [
    ["Theme avg", "The equal-weighted average move of the theme's companies -- each counts once, whatever its size."],
    ["vs benchmark", "Theme average minus the benchmark ETF's move today."],
    ["Beat", "How many companies did better than the benchmark today. Breadth: is the theme's move broad or carried by one or two names?"],
    ["Spread", "Standard deviation of the companies' moves. Low means they moved together; high means they went their own ways."],
    ["vs peers", "A company's move minus the median move of the other companies in its theme -- the typical peer. Cap-weighted ETFs are dominated by their largest holdings, and in a small group one extreme name would decide an average, so this is the cleaner comparison."],
    ["Attention", "Each company's rank within its theme: points for the size of the move (8 a point, " +
      "up to 45), 12 if it moved 1.5 points or more away from its peers, 25 if it reports within a " +
      "week (12 within two), and 3 a headline up to 12. 45 or more needs attention; 20 or more is " +
      "worth a look. Hover a company's tag for its breakdown."],
    ["With theme / Partly shared / Own move", "Compares a company's move with its peers' median. The gap " +
      "between them, as a share of the larger move, decides: up to 40% (or under a point) it tracked its theme; " +
      "60% or more it diverged -- moved alone, against its peers, or held up while they fell; in between is " +
      "partly shared. If neither moved 1%, it's quiet."],
  ].forEach(([term, text]) => {
    const p = el("p");
    p.appendChild(el("strong", null, term + ". "));
    p.appendChild(document.createTextNode(text));
    guide.appendChild(p);
  });
  return guide;
}

function themeStat(label, value, cls, title) {
  const stat = el("div", "tstat");
  stat.appendChild(el("span", "tstat-label", label));
  stat.appendChild(el("span", "tstat-value " + (cls || ""), value));
  if (title) stat.title = title;
  return stat;
}

function buildThemeStats(block) {
  const s = block.summary || {};
  const bench = block.benchmark || {};
  const stats = el("div", "tstats");
  stats.appendChild(themeStat("Theme avg", pct(s.average), toneClass(s.average),
                              "Equal-weighted average move of the theme's companies."));
  stats.appendChild(themeStat(`vs ${bench.ticker}`, pts(s.vs_benchmark), toneClass(s.vs_benchmark),
                              `Theme average minus ${bench.ticker}'s move today.`));
  stats.appendChild(themeStat(`Beat ${bench.ticker}`,
                              s.beat_count === null || s.beat_count === undefined ? "--" : `${s.beat_count} of ${s.count}`,
                              "", `Companies that did better than ${bench.ticker} today.`));
  stats.appendChild(themeStat("Spread", s.dispersion === null || s.dispersion === undefined ? "--" : num(s.dispersion) + "pt",
                              "", "Standard deviation of today's moves: low means they moved together."));
  return stats;
}

function buildThemeBlock(block) {
  const card = el("section", "tblock");
  card.setAttribute("aria-label", block.name);

  const head = el("div", "tblock-head");
  const name = el("a", "tblock-name", block.name);
  name.href = themeHash(block.id);
  head.appendChild(name);
  const bench = block.benchmark || {};
  const benchLine = el("span", "tblock-bench");
  benchLine.appendChild(document.createTextNode(bench.ticker + " "));
  benchLine.appendChild(el("span", toneClass(bench.change_percent),
                           bench.available ? pct(bench.change_percent) : "unavailable"));
  head.appendChild(benchLine);
  card.appendChild(head);

  if (!block.rows.length) {
    card.appendChild(el("p", "empty-inline", "No companies yet."));
  } else {
    card.appendChild(buildThemeStats(block));

    if (block.earnings_soon && block.earnings_soon.length) {
      const soon = el("p", "tblock-earnings");
      soon.appendChild(el("span", "tblock-earnings-label", "Reporting this week"));
      block.earnings_soon.forEach((e) => {
        const tag = el("a", "ticker-tag", e.days === 0 ? `${e.ticker} today` : `${e.ticker} · ${e.days}d`);
        tag.href = stockHash(e.ticker);
        soon.appendChild(tag);
      });
      card.appendChild(soon);
    }

    const rows = el("div", "tblock-rows");
    block.rows.slice(0, 3).forEach((row) => rows.appendChild(buildCompactRow(row)));
    card.appendChild(rows);
  }

  const more = el("a", "tblock-more",
                  block.rows.length > 3 ? `All ${block.rows.length} companies →` : "Open theme →");
  more.href = themeHash(block.id);
  card.appendChild(more);
  return card;
}

function buildCompactRow(row) {
  const level = row.attention ? row.attention.level : "quiet";
  const link = el("a", `crow level-${level}`);
  link.href = stockHash(row.ticker);
  link.title = attentionTitle(row.attention);

  const who = el("div", "crow-who");
  who.appendChild(el("span", "crow-ticker", row.ticker));
  if (row.role) who.appendChild(el("span", "crow-role", row.role));
  link.appendChild(who);

  const change = row.price ? row.price.change_percent : null;
  link.appendChild(el("span", "crow-delta " + toneClass(change), row.price ? pct(change) : "--"));

  const rel = row.relative || {};
  const vs = el("span", "crow-vs " + toneClass(rel.vs_peers), pts(rel.vs_peers));
  vs.title = "Move minus its peers' median move";
  link.appendChild(vs);
  link.appendChild(attributionTag(rel.attribution));
  return link;
}

function buildNewThemeForm() {
  const box = el("details", "panel new-theme");
  box.appendChild(el("summary", null, "+ New theme"));

  const form = el("form", "form-grid");
  const name = labelledInput(form, "Name", "e.g. Cybersecurity", 40);
  const bench = labelledInput(form, "Benchmark ETF", "e.g. SPY", 12);
  bench.value = "SPY";
  bench.setAttribute("list", "benchmark-suggestions");
  const desc = labelledInput(form, "What ties it together (optional)", "The shared driver", 300);

  const list = el("datalist");
  list.id = "benchmark-suggestions";
  BENCHMARK_SUGGESTIONS.forEach(([t, label]) => {
    const opt = el("option");
    opt.value = t;
    opt.label = label;
    list.appendChild(opt);
  });
  form.appendChild(list);

  const error = el("p", "form-error");
  error.hidden = true;
  const submit = el("button", "button-primary", "Create theme");
  submit.type = "submit";
  form.appendChild(submit);
  form.appendChild(error);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    submit.disabled = true;
    const { ok, data } = await api("POST", "/api/themes",
                                   { name: name.value, benchmark: bench.value, description: desc.value });
    submit.disabled = false;
    if (!ok) {
      error.textContent = data.error || "Could not create the theme.";
      error.hidden = false;
      return;
    }
    state.themes = data.themes;
    renderNavThemes();
    const created = data.themes[data.themes.length - 1];
    toast(`Created ${created.name}. Add its companies here.`);
    go(themeHash(created.id));
  });
  box.appendChild(form);
  return box;
}

function labelledInput(form, label, placeholder, maxLength) {
  const wrap = el("label", "field");
  wrap.appendChild(el("span", "field-label", label));
  const input = el("input", "field-input");
  input.type = "text";
  input.placeholder = placeholder;
  input.maxLength = maxLength;
  input.autocomplete = "off";
  wrap.appendChild(input);
  form.appendChild(wrap);
  return input;
}

/* ---------------- theme page ----------------

   The second layer: everything about one theme. How it did against its
   benchmark, each company against the benchmark and against its peers,
   and the controls to change what's in it. */

const THEME_TABS = [
  ["today", "Today"],
  ["performance", "Performance"],
  ["earnings", "Earnings"],
  ["peers", "Peers"],
];

async function showTheme(themeId, tab) {
  tab = THEME_TABS.some(([key]) => key === tab) ? tab : "today";
  const token = beginView("theme", "theme:" + themeId);
  state.themeId = themeId;
  setActiveNav("theme:" + themeId);

  const config = state.themes.find((t) => t.id === themeId);
  if (!config) {
    setTitle("Theme not found");
    viewEl.replaceChildren(el("p", "empty", `There is no theme '${themeId}'.`));
    return;
  }
  setTitle(config.name);

  const frag = document.createDocumentFragment();
  const back = el("a", "back", "← Home");
  back.href = "#/";
  frag.appendChild(back);
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, config.name));
  frag.appendChild(head);
  if (config.description) frag.appendChild(el("p", "view-sub", config.description));
  frag.appendChild(buildTabs(THEME_TABS, tab, (key) => themeHash(themeId) + (key === "today" ? "" : "/" + key)));

  const holder = el("div", "tab-body");
  holder.appendChild(el("p", "loading-text", tab === "today" ? "Loading theme..." : "Loading..."));
  frag.appendChild(holder);
  viewEl.replaceChildren(frag);

  const url = "/api/theme/" + encodeURIComponent(themeId) + (tab === "today" ? "" : "/" + tab);
  const { ok, data } = await api("GET", url);
  if (!isCurrent(token)) return;
  if (!ok) {
    holder.replaceChildren(el("p", "empty", data.error || "Could not load this theme."));
    return;
  }
  if (tab === "today") renderThemeToday(holder, data);
  else if (tab === "performance") renderThemePerformance(holder, data);
  else if (tab === "earnings") renderThemeEarnings(holder, data);
  else renderThemePeers(holder, data);
}

function renderThemeToday(holder, data) {
  const frag = document.createDocumentFragment();
  const bench = data.benchmark || {};
  const summary = el("div", "panel theme-summary");
  const benchStat = themeStat("Benchmark", `${bench.ticker} ${bench.available ? pct(bench.change_percent) : "unavailable"}`,
                              toneClass(bench.change_percent), "The theme's benchmark ETF, today.");
  const stats = buildThemeStats(data);
  stats.prepend(benchStat);
  summary.appendChild(stats);
  const note = sessionNote();
  if (note) summary.appendChild(note);
  const minPeers = (state.limits && state.limits.stocks_for_peers) || 3;
  if (data.rows.length && data.rows.length < minPeers) {
    summary.appendChild(el("p", "form-hint",
      `Add at least ${minPeers} companies: below that, a company's "peers" would be one other stock.`));
  }
  frag.appendChild(summary);

  if (!data.rows.length) {
    frag.appendChild(el("p", "empty", "No companies in this theme yet. Add the first one below."));
  } else {
    frag.appendChild(el("p", "section-heading", "Companies, by what needs attention today"));
    const list = el("div", "rows");
    data.rows.forEach((row) => {
      list.appendChild(buildThemeRow(row, data));
      if (!DEMO) list.appendChild(buildEditPanel(row, data));
    });
    frag.appendChild(list);
  }

  if (!DEMO) {
    frag.appendChild(buildAddCompanyForm(data));
    frag.appendChild(buildThemeSettings(data));
  }
  holder.replaceChildren(frag);

  data.rows.forEach((row) => {
    const canvas = holder.querySelector(`canvas[data-ticker="${cssEscape(row.ticker)}"]`);
    if (canvas) drawSparkline(canvas, row.history || []);
  });
}

/* ---------------- theme tab: performance ---------------- */

function renderThemePerformance(holder, data) {
  const periods = data.periods || [];
  let period = periods.includes(state.perfPeriod) ? state.perfPeriod : "3M";

  const draw = () => {
    const frag = document.createDocumentFragment();
    frag.appendChild(el("p", "view-sub",
      "Each company's return over the window, against the theme's ETF and against its peers -- the " +
      "median return of the other companies in the theme over the same window."));

    const picker = el("div", "segmented");
    picker.setAttribute("role", "group");
    picker.setAttribute("aria-label", "Window");
    periods.forEach((p) => {
      const b = el("button", "segment" + (p === period ? " is-active" : ""), p);
      b.type = "button";
      b.setAttribute("aria-pressed", String(p === period));
      b.addEventListener("click", () => {
        period = p;
        state.perfPeriod = p;
        draw();
      });
      picker.appendChild(b);
    });
    frag.appendChild(picker);

    const bench = data.benchmark || {};
    const s = (data.summary || {})[period] || {};
    const benchReturn = (bench.returns || {})[period];
    const stats = el("div", "panel theme-summary");
    const line = el("div", "tstats");
    line.appendChild(themeStat(`${bench.ticker}, ${period}`, pct(benchReturn), toneClass(benchReturn)));
    line.appendChild(themeStat("Theme avg", pct(s.average), toneClass(s.average), "Equal-weighted average return."));
    line.appendChild(themeStat(`vs ${bench.ticker}`, pts(s.vs_benchmark), toneClass(s.vs_benchmark)));
    line.appendChild(themeStat(`Beat ${bench.ticker}`,
      s.beat_count === null || s.beat_count === undefined ? "--" : `${s.beat_count} of ${s.count}`));
    line.appendChild(themeStat("Spread", s.dispersion === null || s.dispersion === undefined ? "--" : num(s.dispersion) + "pt",
                               "", "Standard deviation of the companies' returns over the window."));
    stats.appendChild(line);
    frag.appendChild(stats);

    const rows = (data.rows || []).map((r) => ({ ...r, cell: r.periods[period] || {} }))
      .sort((a, b) => (b.cell.vs_peers ?? -Infinity) - (a.cell.vs_peers ?? -Infinity));
    const extent = Math.max(1, ...rows.map((r) => Math.abs(r.cell.vs_peers || 0)));

    const table = el("table", "data-table");
    const thead = el("thead");
    const hr = el("tr");
    ["Company", `Return, ${period}`, `vs ${bench.ticker}`, "vs peers", ""].forEach((h, i) => {
      const th = el("th", i === 0 ? "" : "num", h);
      th.scope = "col";
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = el("tbody");
    rows.forEach((r) => {
      const tr = el("tr", "is-link");
      tr.tabIndex = 0;
      const open = () => go(stockHash(r.ticker));
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
      const who = el("td");
      who.appendChild(el("span", "cell-ticker", r.ticker));
      if (r.role) who.appendChild(el("span", "cell-role", r.role));
      tr.appendChild(who);
      tr.appendChild(el("td", "num " + toneClass(r.cell.return), pct(r.cell.return)));
      tr.appendChild(el("td", "num " + toneClass(r.cell.vs_benchmark), pts(r.cell.vs_benchmark)));
      const vs = el("td", "num bar-cell");
      vs.appendChild(divergingBar(r.cell.vs_peers, extent));
      vs.appendChild(el("span", toneClass(r.cell.vs_peers), pts(r.cell.vs_peers)));
      tr.appendChild(vs);
      const tagCell = el("td", "num");
      tagCell.appendChild(attributionTag(r.cell.attribution));
      tr.appendChild(tagCell);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    const wrap = el("div", "panel table-wrap");
    wrap.appendChild(table);
    frag.appendChild(wrap);

    frag.appendChild(el("p", "metric-note",
      "Windows are counted in trading sessions (1M = 21, 3M = 63, 6M = 126, 1Y = 252); a window " +
      "longer than a company's history shows --. Peers are summarised by their median, so one " +
      "extreme name can't decide the comparison on its own."));
    holder.replaceChildren(frag);
  };
  draw();
}

// A bar growing left or right from the centre: the gap to peers at a glance.
function divergingBar(value, extent) {
  const track = el("span", "bar-track");
  track.setAttribute("aria-hidden", "true");
  if (value === null || value === undefined) return track;
  const bar = el("span", "bar " + (value >= 0 ? "bar-up" : "bar-down"));
  bar.style.width = Math.min(50, (Math.abs(value) / extent) * 50) + "%";
  track.appendChild(bar);
  return track;
}

/* ---------------- theme tab: earnings ---------------- */

const SERIES_PALETTE = ["#2a78d6", "#7B4B63", "#A15C00", "#3B7F8C", "#6B5CA5", "#8A7278", "#4F6D3A", "#B05E86"];

function correlationWords(rho) {
  const a = Math.abs(rho);
  const strength = a < 0.2 ? "little to no" : a < 0.4 ? "a weak" : a < 0.6 ? "a moderate" : "a strong";
  return a < 0.2 ? "little to no relationship" : `${strength} ${rho > 0 ? "positive" : "negative"} relationship`;
}

function renderThemeEarnings(holder, data) {
  const frag = document.createDocumentFragment();
  const s = data.stats || {};
  const companies = new Set((data.points || []).map((p) => p.ticker)).size;

  const summary = el("div", "panel");
  summary.appendChild(el("h2", null, "Does this theme reward beats?"));
  if (!s.reports) {
    summary.appendChild(el("p", "form-hint", "No reports with both a surprise figure and a market model yet."));
  } else {
    const lines = [
      `${s.reports} reports from ${companies} compan${companies === 1 ? "y" : "ies"} over roughly two years, ` +
      `each reaction measured against that company's own market model.`,
      `${s.beats} beat the EPS estimate; ${s.beats_rewarded} of those ` +
      `(${s.beats ? Math.round((s.beats_rewarded / s.beats) * 100) : 0}%) were followed by a positive abnormal reaction.` +
      (s.misses ? ` ${s.misses} missed, and ${s.misses_punished} of those lagged their model.` : ""),
    ];
    if (s.rank_correlation !== null && s.rank_correlation !== undefined) {
      lines.push(`Rank correlation between the size of the surprise and the abnormal reaction: ` +
                 `${num(s.rank_correlation, 2)} -- ${correlationWords(s.rank_correlation)}. Bigger beats ` +
                 (Math.abs(s.rank_correlation) < 0.2 ? "have not meant bigger reactions here." : "have tended to move with reactions here."));
    } else {
      lines.push(`Fewer than ${s.min_points} reports with both figures -- too few for a correlation.`);
    }
    lines.forEach((t) => summary.appendChild(el("p", "earn-line", t)));
    summary.appendChild(el("p", "metric-note",
      "Reports from a handful of companies, overlapping in time, aren't independent observations: " +
      "read this as a description of the theme's recent history, not a statistical test."));
  }
  frag.appendChild(summary);

  const points = data.points || [];
  let scatter = null;
  if (points.length) {
    const panel = el("div", "panel");
    panel.appendChild(el("h2", null, "Surprise against abnormal reaction"));
    const wrap = el("div", "chart-wrap");
    const canvas = el("canvas", "scatter-chart");
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label",
      `Scatter of ${points.length} earnings reports: EPS surprise against the abnormal reaction. ` +
      `The table below lists each company's figures.`);
    wrap.appendChild(canvas);
    panel.appendChild(wrap);

    const tickers = [...new Set(points.map((p) => p.ticker))];
    const colorOf = Object.fromEntries(tickers.map((t, i) => [t, SERIES_PALETTE[i % SERIES_PALETTE.length]]));
    const legend = el("div", "legend");
    tickers.forEach((t) => {
      const item = el("span", "legend-item");
      const swatch = el("span", "legend-swatch");
      swatch.style.background = colorOf[t];
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(t));
      legend.appendChild(item);
    });
    panel.appendChild(legend);
    panel.appendChild(el("p", "metric-note",
      "Right of the vertical line: beat the estimate. Above the horizontal line: did better than " +
      "the company's market model expected on the reaction session. Surprises beyond " +
      `${X_CLIP[0]}% or +${X_CLIP[1]}% are drawn hollow at the axis edge. Hover a point for the report.`));
    frag.appendChild(panel);
    scatter = { canvas, points, colorOf };
  }

  const table = el("table", "data-table");
  const thead = el("thead");
  const hr = el("tr");
  ["Company", "Next report", "Latest report", "Surprise", "Abnormal reaction", "Run-up before",
   "Typical |abnormal|", "Beat but lagged"].forEach((h, i) => {
    const th = el("th", i === 0 ? "" : "num", h);
    th.scope = "col";
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  (data.rows || []).forEach((r) => {
    const latest = r.latest || {};
    const tr = el("tr", "is-link");
    tr.tabIndex = 0;
    const open = () => go(stockHash(r.ticker) + "/earnings");
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    const who = el("td");
    who.appendChild(el("span", "cell-ticker", r.ticker));
    tr.appendChild(who);
    tr.appendChild(el("td", "num", r.next_report_days === null || r.next_report_days === undefined
      ? "--" : r.next_report_days === 0 ? "today" : `in ${r.next_report_days}d`));
    tr.appendChild(el("td", "num", latest.date ? formatDate(latest.date) : "--"));
    tr.appendChild(el("td", "num " + toneClass(latest.surprise_percent),
      latest.surprise_percent === null || latest.surprise_percent === undefined ? "--" : pct(latest.surprise_percent)));
    const ar = latest.abnormal_move;
    tr.appendChild(el("td", "num " + toneClass(ar), ar === null || ar === undefined ? "--"
      : pct(ar) + (latest.standardized !== null && latest.standardized !== undefined ? `  (${num(latest.standardized, 1)} sd)` : "")));
    tr.appendChild(el("td", "num " + toneClass(latest.runup_abnormal),
      latest.runup_abnormal === null || latest.runup_abnormal === undefined ? "--" : pct(latest.runup_abnormal)));
    tr.appendChild(el("td", "num", r.median_abs_abnormal === null || r.median_abs_abnormal === undefined
      ? "--" : "±" + num(r.median_abs_abnormal, 1) + "%"));
    tr.appendChild(el("td", "num", r.beat_count ? `${r.beat_but_lagged || 0} of ${r.beat_count}` : "--"));
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  const wrap = el("div", "panel table-wrap");
  wrap.appendChild(el("h2", null, "By company"));
  wrap.appendChild(table);
  wrap.appendChild(el("p", "metric-note",
    "Abnormal reaction: the move on the first session that could react, minus what the company's " +
    "market model predicted given SPY that session; sd says how many of its ordinary daily moves " +
    "that is. Run-up: the abnormal move over the 20 sessions before the report. Click a company " +
    "for its full history."));
  frag.appendChild(wrap);

  holder.replaceChildren(frag);
  if (scatter) setupScatter(scatter.canvas, scatter.points, scatter.colorOf);
}

const SCATTER_PAD = { left: 52, right: 16, top: 14, bottom: 34 };
const X_CLIP = [-40, 60];

// Round-number ticks that fit the range, never closer than `minGap` px.
function niceTicks(lo, hi, scale, minGap) {
  const steps = [5, 10, 20, 25, 50, 100];
  const step = steps.find((st) => Math.abs(scale(st) - scale(0)) >= minGap) || 100;
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  return ticks;
}

function scatterScales(canvas, points) {
  const cssW = canvas.clientWidth || 600;
  const cssH = canvas.clientHeight || 300;
  // Surprises have long tails (a 300% beat on a tiny estimate); clip the
  // axis and draw outliers at its edge rather than squash everything else.
  const xs = points.map((p) => Math.max(X_CLIP[0], Math.min(X_CLIP[1], p.surprise)));
  const xMin = Math.min(0, ...xs) - 2;
  const xMax = Math.max(0, ...xs) + 2;
  const yExt = Math.max(2, ...points.map((p) => Math.abs(p.abnormal))) * 1.1;
  const plotW = cssW - SCATTER_PAD.left - SCATTER_PAD.right;
  const plotH = cssH - SCATTER_PAD.top - SCATTER_PAD.bottom;
  return {
    cssW, cssH,
    x: (v) => SCATTER_PAD.left + ((Math.max(X_CLIP[0], Math.min(X_CLIP[1], v)) - xMin) / (xMax - xMin)) * plotW,
    y: (v) => SCATTER_PAD.top + plotH / 2 - (v / yExt) * (plotH / 2),
    xMin, xMax, yExt, plotW, plotH,
  };
}

function drawScatter(canvas, points, colorOf, hoverIndex) {
  const dpr = window.devicePixelRatio || 1;
  const sc = scatterScales(canvas, points);
  canvas.width = sc.cssW * dpr;
  canvas.height = sc.cssH * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, sc.cssW, sc.cssH);

  ctx.strokeStyle = COLORS.axis;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(SCATTER_PAD.left, Math.round(sc.y(0)) + 0.5);
  ctx.lineTo(sc.cssW - SCATTER_PAD.right, Math.round(sc.y(0)) + 0.5);
  ctx.moveTo(Math.round(sc.x(0)) + 0.5, SCATTER_PAD.top);
  ctx.lineTo(Math.round(sc.x(0)) + 0.5, SCATTER_PAD.top + sc.plotH);
  ctx.stroke();

  ctx.font = "11px system-ui, -apple-system, sans-serif";
  ctx.fillStyle = COLORS.muted;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  [sc.yExt / 1.1, 0, -sc.yExt / 1.1].forEach((v) => {
    ctx.fillText((v > 0 ? "+" : "") + v.toFixed(0) + "%", SCATTER_PAD.left - 8, sc.y(v));
  });
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  niceTicks(sc.xMin, sc.xMax, sc.x, 48).forEach((v) => {
    const edge = v >= X_CLIP[1] ? "+" : "";  // the clipped edge holds everything beyond it
    ctx.fillText((v > 0 ? "+" : "") + v.toFixed(0) + "%" + edge, sc.x(v), SCATTER_PAD.top + sc.plotH + 6);
  });
  ctx.fillText("EPS surprise", SCATTER_PAD.left + sc.plotW / 2, SCATTER_PAD.top + sc.plotH + 19);
  ctx.save();
  ctx.translate(12, SCATTER_PAD.top + sc.plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("Abnormal reaction", 0, -6);
  ctx.restore();

  points.forEach((p, i) => {
    const clipped = p.surprise < X_CLIP[0] || p.surprise > X_CLIP[1];
    ctx.beginPath();
    ctx.arc(sc.x(p.surprise), sc.y(p.abnormal), i === hoverIndex ? 6 : 4.5, 0, Math.PI * 2);
    ctx.globalAlpha = i === hoverIndex || hoverIndex === null || hoverIndex === undefined ? 0.85 : 0.35;
    if (clipped) {
      // Hollow: this point sits at the axis edge, not at its true surprise.
      ctx.lineWidth = 2;
      ctx.strokeStyle = colorOf[p.ticker];
      ctx.stroke();
    } else {
      ctx.fillStyle = colorOf[p.ticker];
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = COLORS.surface;
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  });
}

function setupScatter(canvas, points, colorOf) {
  drawScatter(canvas, points, colorOf, null);
  if (window.ResizeObserver) new ResizeObserver(() => drawScatter(canvas, points, colorOf, null)).observe(canvas);
  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const sc = scatterScales(canvas, points);
    let best = null;
    let bestDist = 10;
    points.forEach((p, i) => {
      const d = Math.hypot(sc.x(p.surprise) - (e.clientX - rect.left), sc.y(p.abnormal) - (e.clientY - rect.top));
      if (d < bestDist) { best = i; bestDist = d; }
    });
    drawScatter(canvas, points, colorOf, best);
    if (best === null) { hideTooltip(); return; }
    const p = points[best];
    tooltipEl.replaceChildren();
    tooltipEl.appendChild(el("div", "tip-value", `${p.ticker} · ${formatLongDate(p.date)}`));
    tooltipEl.appendChild(el("div", "tip-label", `EPS ${p.surprise >= 0 ? "beat" : "missed"} by ${Math.abs(p.surprise).toFixed(1)}%`));
    tooltipEl.appendChild(el("div", "tip-label",
      `Abnormal reaction ${pct(p.abnormal)}` + (p.standardized !== null ? ` (${num(p.standardized, 1)} sd)` : "")));
    tooltipEl.hidden = false;
    const tip = tooltipEl.getBoundingClientRect();
    let left = e.clientX + 14;
    if (left + tip.width > window.innerWidth - 8) left = e.clientX - tip.width - 14;
    tooltipEl.style.left = left + "px";
    tooltipEl.style.top = Math.max(8, e.clientY - tip.height - 12) + "px";
  });
  canvas.addEventListener("pointerleave", () => { drawScatter(canvas, points, colorOf, null); hideTooltip(); });
}

/* ---------------- theme tab: peers ---------------- */

const METRIC_NOTES = {
  market_cap: "Share price times shares outstanding.",
  forward_pe: "Price divided by next fiscal year's consensus EPS.",
  ev_to_sales: "Enterprise value (market cap plus net debt) divided by the last twelve months' revenue.",
  revenue_growth_percent: "Latest quarter's revenue against the same quarter a year earlier.",
  gross_margin_percent: "Revenue left after direct costs, last twelve months.",
  operating_margin_percent: "Revenue left after running costs too, last twelve months.",
  estimate_change_90d: "Change in next fiscal year's consensus EPS estimate over 90 days.",
  net_revisions_30d: "Analysts raising next year's EPS estimate minus those cutting it, last 30 days.",
};

function formatMetric(value, unit) {
  if (value === null || value === undefined) return "--";
  if (unit === "money") return "$" + bigMoney(value);
  if (unit === "x") return num(value, 1) + "x";
  if (unit === "%") return num(value, 1) + "%";
  if (unit === "count") return (value > 0 ? "+" : "") + num(value, 0);
  return String(value);
}

function renderThemePeers(holder, data) {
  const frag = document.createDocumentFragment();
  frag.appendChild(el("p", "view-sub",
    "Valuation, growth, profitability and the direction of analyst estimates, side by side, with " +
    "the theme's median. Hover a column heading for its definition."));
  const panel = el("div", "panel table-wrap");
  panel.appendChild(buildPeerTable(data, null));
  frag.appendChild(panel);
  holder.replaceChildren(frag);
}

function buildPeerTable(data, highlight) {
  const box = el("div");
  const table = el("table", "data-table peer-table");
  const thead = el("thead");
  const hr = el("tr");
  const th0 = el("th", null, "Company");
  th0.scope = "col";
  hr.appendChild(th0);
  data.metrics.forEach((m) => {
    const th = el("th", "num", m.label);
    th.scope = "col";
    th.title = METRIC_NOTES[m.key] || "";
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);

  const notes = [];
  const tbody = el("tbody");
  data.rows.forEach((r) => {
    const tr = el("tr", "is-link" + (r.ticker === highlight ? " is-self" : ""));
    tr.tabIndex = 0;
    const open = () => go(stockHash(r.ticker) + "/fundamentals");
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    const who = el("td");
    who.appendChild(el("span", "cell-ticker", r.ticker));
    (r.flags || []).forEach((f) => {
      notes.push([r.ticker, f]);
      const mark = el("sup", "flag-mark", String(notes.length));
      mark.title = f;
      who.appendChild(mark);
    });
    tr.appendChild(who);
    data.metrics.forEach((m) => {
      const v = r.values[m.key];
      const signed = m.unit === "count" || m.key === "estimate_change_90d";
      tr.appendChild(el("td", "num " + (signed ? toneClass(v) : ""), formatMetric(v, m.unit)));
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  const tfoot = el("tfoot");
  const fr = el("tr");
  fr.appendChild(el("th", null, "Theme median"));
  data.metrics.forEach((m) => fr.appendChild(el("td", "num", formatMetric(data.medians[m.key], m.unit))));
  tfoot.appendChild(fr);
  table.appendChild(tfoot);
  box.appendChild(table);

  if (notes.length) {
    const list = el("ol", "flag-notes");
    notes.forEach(([ticker, text]) => list.appendChild(el("li", null, `${ticker}: ${text}`)));
    box.appendChild(list);
  }
  box.appendChild(el("p", "metric-note",
    "From Yahoo Finance. Margins are the last twelve months; growth is the latest quarter against a " +
    "year earlier; estimates are next fiscal year's consensus."));
  return box;
}

function cssEscape(value) {
  return String(value).replace(/["\\]/g, "\\$&");
}

function buildThemeRow(row, theme) {
  const level = row.attention ? row.attention.level : "quiet";
  const item = el("div", `row theme-row level-${level}`);
  item.tabIndex = 0;
  item.setAttribute("role", "link");
  item.setAttribute("aria-label", `${row.ticker}, open details`);
  const open = () => go(stockHash(row.ticker));
  item.addEventListener("click", open);
  item.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });

  const left = el("div");
  left.appendChild(el("div", "ticker", row.ticker));
  const tag = el("span", "attention-tag",
                 level === "high" ? "Needs attention" : level === "medium" ? "Worth a look" : "Quiet");
  tag.title = attentionTitle(row.attention);
  left.appendChild(tag);
  if (row.role) left.appendChild(el("span", "row-role", row.role));
  item.appendChild(left);

  const middle = el("div");
  if (row.error) {
    middle.appendChild(el("div", "row-error", row.error));
  } else {
    middle.appendChild(el("div", "headline", row.top_headline || "No recent headlines"));
    const factors = el("div", "factors");
    (row.attention ? row.attention.factors : []).forEach((f) => {
      factors.appendChild(el("span", "chip " + (f.tone === "neutral" ? "" : f.tone), f.label));
    });
    middle.appendChild(factors);
  }
  if (row.note) middle.appendChild(el("div", "row-note", row.note));
  item.appendChild(middle);

  item.appendChild(el("div", "price", row.price ? money(row.price.price) : "--"));
  const change = row.price ? row.price.change_percent : null;
  item.appendChild(el("div", "delta " + toneClass(change), row.price ? pct(change) : "--"));

  const rel = row.relative || {};
  const relCell = el("div", "rel-cell");
  const peersLine = el("div", "rel-line");
  peersLine.appendChild(el("span", "rel-label", "vs peers"));
  peersLine.appendChild(el("span", "rel-value " + toneClass(rel.vs_peers), pts(rel.vs_peers)));
  relCell.appendChild(peersLine);
  const benchLine = el("div", "rel-line");
  benchLine.appendChild(el("span", "rel-label", "vs " + theme.benchmark.ticker));
  benchLine.appendChild(el("span", "rel-value " + toneClass(rel.vs_benchmark), pts(rel.vs_benchmark)));
  relCell.appendChild(benchLine);
  relCell.appendChild(attributionTag(rel.attribution));
  item.appendChild(relCell);

  const sparkCell = el("div", "spark-cell");
  const canvas = el("canvas", "spark");
  canvas.dataset.ticker = row.ticker;
  canvas.width = 88;
  canvas.height = 30;
  sparkCell.appendChild(canvas);
  sparkCell.appendChild(el("span", "spark-label", "1 month"));
  item.appendChild(sparkCell);

  if (DEMO) {
    item.appendChild(el("div"));  // keeps the grid's last column
    return item;
  }
  const edit = el("button", "row-edit", "Edit");
  edit.type = "button";
  edit.setAttribute("aria-expanded", "false");
  edit.setAttribute("aria-label", `Edit ${row.ticker}`);
  edit.addEventListener("click", (e) => {
    e.stopPropagation();
    const panel = item.nextElementSibling;
    panel.hidden = !panel.hidden;
    edit.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) panel.querySelector("input").focus();
  });
  item.appendChild(edit);
  return item;
}

// Sits after its row, not inside it: the row is itself clickable, and form
// controls nested in a clickable element can't be used reliably.
function buildEditPanel(row, theme) {
  const panel = el("div", "edit-panel");
  panel.hidden = true;

  const noteForm = el("form", "edit-line");
  const note = el("input", "field-input");
  note.type = "text";
  note.maxLength = 200;
  note.value = row.note || "";
  note.placeholder = "Why you're watching it, in your words";
  note.setAttribute("aria-label", `Note on ${row.ticker}`);
  const save = el("button", "button-secondary", "Save note");
  save.type = "submit";
  noteForm.appendChild(note);
  noteForm.appendChild(save);
  noteForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await changeStock(theme.id, row.ticker, { note: note.value }, "Note saved.");
  });
  panel.appendChild(noteForm);

  const moveLine = el("div", "edit-line");
  const select = el("select", "field-input");
  select.setAttribute("aria-label", `Move ${row.ticker} to another theme`);
  const others = state.themes.filter((t) => t.id !== theme.id);
  select.appendChild(new Option(others.length ? "Move to another theme..." : "No other themes", ""));
  others.forEach((t) => select.appendChild(new Option(t.name, t.id)));
  const move = el("button", "button-secondary", "Move");
  move.type = "button";
  move.disabled = !others.length;
  move.addEventListener("click", async () => {
    if (!select.value) return;
    const target = others.find((t) => t.id === select.value);
    await changeStock(theme.id, row.ticker, { move_to: select.value },
                      `${row.ticker} moved to ${target ? target.name : "the other theme"}.`);
  });
  const remove = el("button", "button-danger", "Remove from theme");
  remove.type = "button";
  remove.addEventListener("click", async () => {
    const { ok, data } = await api("DELETE",
      `/api/themes/${encodeURIComponent(theme.id)}/stocks/${encodeURIComponent(row.ticker)}`);
    afterThemeChange(ok, data, `${row.ticker} removed from ${theme.name}.`);
  });
  moveLine.appendChild(select);
  moveLine.appendChild(move);
  moveLine.appendChild(remove);
  panel.appendChild(moveLine);
  return panel;
}

async function changeStock(themeId, ticker, body, message) {
  const { ok, data } = await api("PATCH",
    `/api/themes/${encodeURIComponent(themeId)}/stocks/${encodeURIComponent(ticker)}`, body);
  afterThemeChange(ok, data, message);
}

function afterThemeChange(ok, data, message) {
  if (!ok) {
    toast(data.error || "That change didn't save.");
    return;
  }
  state.themes = data.themes;
  state.detail = null;
  renderNavThemes();
  toast(message);
  route();
}

function buildAddCompanyForm(theme) {
  const box = el("div", "panel");
  box.appendChild(el("h2", null, "Add a company"));
  const form = el("form", "form-grid");
  const ticker = labelledInput(form, "Ticker", "e.g. LRCX", 12);
  const note = labelledInput(form, "Why you're watching it (optional)", "In your words", 200);
  const submit = el("button", "button-primary", "Add");
  submit.type = "submit";
  const error = el("p", "form-error");
  error.hidden = true;
  form.appendChild(submit);
  form.appendChild(error);
  box.appendChild(el("p", "form-hint",
    "Each company belongs to one theme, so its peer comparison is always against a single group."));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const symbol = ticker.value.trim().toUpperCase();
    if (!symbol) return;
    submit.disabled = true;
    submit.textContent = "Checking...";
    const { ok, data } = await api("POST", `/api/themes/${encodeURIComponent(theme.id)}/stocks`,
                                   { ticker: symbol, note: note.value });
    submit.disabled = false;
    submit.textContent = "Add";
    if (!ok) {
      error.textContent = data.error || "Could not add that company.";
      error.hidden = false;
      return;
    }
    afterThemeChange(true, data, `${symbol} added to ${theme.name}.`);
  });
  box.appendChild(form);
  return box;
}

function buildThemeSettings(theme) {
  const box = el("details", "panel theme-settings");
  box.appendChild(el("summary", null, "Theme settings"));
  const form = el("form", "form-grid");
  const name = labelledInput(form, "Name", "", 40);
  name.value = theme.name;
  const bench = labelledInput(form, "Benchmark ETF", "", 12);
  bench.value = theme.benchmark.ticker;
  bench.setAttribute("list", "benchmark-suggestions-settings");
  const list = el("datalist");
  list.id = "benchmark-suggestions-settings";
  BENCHMARK_SUGGESTIONS.forEach(([t, label]) => {
    const opt = el("option");
    opt.value = t;
    opt.label = label;
    list.appendChild(opt);
  });
  form.appendChild(list);
  const desc = labelledInput(form, "What ties it together", "", 300);
  desc.value = theme.description || "";
  const save = el("button", "button-primary", "Save changes");
  save.type = "submit";
  const error = el("p", "form-error");
  error.hidden = true;
  form.appendChild(save);
  form.appendChild(error);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { ok, data } = await api("PATCH", "/api/themes/" + encodeURIComponent(theme.id),
                                   { name: name.value, benchmark: bench.value, description: desc.value });
    if (!ok) {
      error.textContent = data.error || "Could not save.";
      error.hidden = false;
      return;
    }
    afterThemeChange(true, data, "Theme updated.");
  });
  box.appendChild(form);

  const del = el("button", "button-danger", "Delete this theme");
  del.type = "button";
  del.addEventListener("click", async () => {
    const count = theme.rows.length;
    const ask = count
      ? `Delete ${theme.name}? Its ${count} compan${count === 1 ? "y" : "ies"} will stop being tracked.`
      : `Delete ${theme.name}?`;
    if (!window.confirm(ask)) return;
    const { ok, data } = await api("DELETE", "/api/themes/" + encodeURIComponent(theme.id));
    if (!ok) {
      toast(data.error || "Could not delete the theme.");
      return;
    }
    state.themes = data.themes;
    renderNavThemes();
    toast(`Deleted ${theme.name}.`);
    go("#/");
  });
  box.appendChild(del);
  return box;
}

/* ---------------- add-to-theme menu ----------------

   Used wherever a company not yet tracked appears -- Discover, search, a
   stock page -- since adding now means choosing which theme it joins. */

function openThemeMenu(anchor, ticker) {
  closeThemeMenu();
  const menu = el("div", "theme-menu");
  menu.id = "theme-menu";
  menu.setAttribute("role", "menu");
  menu.appendChild(el("p", "theme-menu-title", `Add ${ticker} to`));
  const error = el("p", "form-error");
  error.hidden = true;

  state.themes.forEach((t) => {
    const item = el("button", "theme-menu-item", t.name);
    item.type = "button";
    item.setAttribute("role", "menuitem");
    item.addEventListener("click", async (e) => {
      e.stopPropagation();
      item.disabled = true;
      const { ok, data } = await api("POST", `/api/themes/${encodeURIComponent(t.id)}/stocks`, { ticker });
      if (!ok) {
        item.disabled = false;
        error.textContent = data.error || "Could not add it.";
        error.hidden = false;
        return;
      }
      closeThemeMenu();
      afterThemeChange(true, data, `${ticker} added to ${t.name}.`);
    });
    menu.appendChild(item);
  });
  if (!state.themes.length) menu.appendChild(el("p", "form-hint", "Create a theme on the home page first."));
  menu.appendChild(error);

  document.body.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  const width = menu.offsetWidth;
  menu.style.top = window.scrollY + rect.bottom + 6 + "px";
  menu.style.left = Math.max(8, Math.min(window.scrollX + rect.right - width,
                                         window.innerWidth - width - 8)) + "px";
  const first = menu.querySelector("button");
  if (first) first.focus();

  setTimeout(() => document.addEventListener("click", closeOnOutside), 0);
}

function closeOnOutside(e) {
  const menu = document.getElementById("theme-menu");
  if (menu && !menu.contains(e.target)) closeThemeMenu();
}

function closeThemeMenu() {
  const menu = document.getElementById("theme-menu");
  if (menu) menu.remove();
  document.removeEventListener("click", closeOnOutside);
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeThemeMenu();
});

/* Rows for names outside your themes (Discover, search). */
function buildRow(row, opts) {
  const discover = !!(opts && opts.discover);
  const level = row.attention ? row.attention.level : "quiet";
  const item = el("div", `row level-${level}` + (discover ? " is-discover" : ""));
  item.tabIndex = 0;
  item.setAttribute("role", "link");
  item.setAttribute("aria-label", `${row.ticker}, open details`);
  const open = () => go(stockHash(row.ticker));
  item.addEventListener("click", open);
  item.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });

  const left = el("div");
  left.appendChild(el("div", "ticker", row.ticker));
  left.appendChild(el("span", "attention-tag", "Not in your themes"));
  item.appendChild(left);

  const middle = el("div");
  if (row.error) {
    middle.appendChild(el("div", "row-error", row.error));
  } else {
    middle.appendChild(el("div", "headline", row.top_headline || "No recent headlines"));
    const factors = el("div", "factors");
    (row.attention ? row.attention.factors : []).forEach((f) => {
      factors.appendChild(el("span", "chip " + (f.tone === "neutral" ? "" : f.tone), f.label));
    });
    middle.appendChild(factors);
  }
  item.appendChild(middle);

  item.appendChild(el("div", "price", row.price ? money(row.price.price) : "--"));
  const delta = el("div", "delta " + (row.price ? toneClass(row.price.change_percent) : ""),
                   row.price ? pct(row.price.change_percent) : "--");
  item.appendChild(delta);

  const sparkCell = el("div", "spark-cell");
  const canvas = el("canvas", "spark");
  canvas.dataset.ticker = row.ticker;
  canvas.width = 88;
  canvas.height = 30;
  sparkCell.appendChild(canvas);
  sparkCell.appendChild(el("span", "spark-label", "1 month"));
  item.appendChild(sparkCell);

  if (DEMO) {
    item.appendChild(el("div"));
    return item;
  }
  const add = el("button", "add", "+");
  add.type = "button";
  add.title = `Add ${row.ticker} to a theme`;
  add.setAttribute("aria-label", `Add ${row.ticker} to a theme`);
  add.addEventListener("click", (e) => {
    e.stopPropagation();
    openThemeMenu(add, row.ticker);
  });
  item.appendChild(add);
  return item;
}

/* ---------------- detail ---------------- */

/* The stock page, in three tabs. Overview answers "what happened today and
   why might it matter"; Earnings, "how does this company handle reports";
   Fundamentals & peers, "what is the business, and how does it compare". */

const STOCK_TABS = [
  ["overview", "Overview"],
  ["earnings", "Earnings"],
  ["fundamentals", "Fundamentals & peers"],
];

// Pages and tabs share one fetch: switching tabs on the same company
// shouldn't reload it.
const DETAIL_REUSE_MS = 60 * 1000;

async function showDetail(ticker, tab) {
  tab = STOCK_TABS.some(([key]) => key === tab) ? tab : "overview";
  setTitle(ticker);
  const owner = state.themes.find((t) => t.stocks.some((s) => s.ticker === ticker));
  const token = beginView("detail", owner ? "theme:" + owner.id : null);

  let data = null;
  const held = state.detail;
  if (held && held.ticker === ticker && Date.now() - held.at < DETAIL_REUSE_MS) {
    data = held.data;
  } else {
    viewEl.replaceChildren(el("p", "loading-text", `Loading ${ticker}...`));
    const res = await api("GET", `/api/stock/${encodeURIComponent(ticker)}`);
    if (!isCurrent(token)) return;
    if (!res.ok) {
      viewEl.replaceChildren(el("p", "empty", "Could not load " + ticker + ": " + (res.data.error || "")));
      return;
    }
    data = res.data;
    state.detail = { ticker, data, at: Date.now() };
  }

  const frag = document.createDocumentFragment();
  const back = el("a", "back", data.theme ? `← ${data.theme.theme_name}` : "← Home");
  back.href = data.theme ? themeHash(data.theme.theme_id) : "#/";
  frag.appendChild(back);

  const head = el("div", "detail-head");
  head.appendChild(el("h1", null, data.ticker));
  if (data.price) {
    head.appendChild(el("div", "detail-price", money(data.price.price)));
    head.appendChild(
      el("div", "detail-delta " + toneClass(data.price.change_percent),
         `${pct(data.price.change_percent)} ${sessionPhrase()}`)
    );
  } else if (data.price_error) {
    head.appendChild(el("div", "row-error", data.price_error));
  }
  frag.appendChild(head);

  // Market comparison as a stat, not a second chart line: two series on
  // one price axis would be misleading, and the honest comparison here is
  // a single number.
  if (data.price && data.market && data.market.change_percent !== null) {
    const rel = data.price.change_percent - data.market.change_percent;
    frag.appendChild(
      el(
        "p",
        "view-sub",
        `SPY ${pct(data.market.change_percent)} ${sessionPhrase()} — ${data.ticker} is ${
          rel >= 0 ? "outperforming" : "underperforming"
        } the market by ${Math.abs(rel).toFixed(2)} points.`
      )
    );
  }

  frag.appendChild(buildTabs(STOCK_TABS, tab, (key) => stockHash(ticker) + (key === "overview" ? "" : "/" + key)));

  const after = [];  // drawing that needs the canvases in the document
  if (tab === "overview") {
    frag.appendChild(buildThemeContext(data));
    const chart = buildPriceChartPanel(data);
    frag.appendChild(chart.panel);
    frag.appendChild(buildAnalysisNews(data));
    if (chart.history.length >= 2) after.push(() => setupChart(chart.canvas, chart.history));
  } else if (tab === "earnings") {
    frag.appendChild(buildEarningsFacts(data));
    const setupBuilt = buildSetupPanel(data.setup, data.ticker, (data.earnings || {}).days_away);
    if (setupBuilt) {
      frag.appendChild(setupBuilt.panel);
      after.push(() => {
        drawReactionChart(setupBuilt.canvas, setupBuilt.reactions);
        attachReactionHover(setupBuilt.canvas, setupBuilt.reactions);
        if (window.ResizeObserver) {
          new ResizeObserver(() => drawReactionChart(setupBuilt.canvas, setupBuilt.reactions))
            .observe(setupBuilt.canvas);
        }
      });
    } else {
      frag.appendChild(el("p", "empty", (data.setup && data.setup.unavailable_reason)
        ? `No earnings history to show (${data.setup.unavailable_reason}).`
        : "Fewer than three past reports with price data, so there's no pattern to show yet."));
    }
  } else {
    const fundamentals = buildFundamentalsPanel(data);
    if (fundamentals) {
      frag.appendChild(fundamentals.panel);
      if (fundamentals.quarters.length) {
        after.push(() => setupBarChart(fundamentals.barCanvas, fundamentals.quarters));
      }
    }
    const peersHolder = el("div");
    frag.appendChild(peersHolder);
    if (data.theme) after.push(() => loadStockPeers(peersHolder, data, token));
  }

  viewEl.replaceChildren(frag);
  after.forEach((fn) => fn());
}

// Navigation tabs: plain links, so each tab has its own address.
function buildTabs(items, active, hrefFor) {
  const nav = el("nav", "tabs");
  nav.setAttribute("aria-label", "Sections");
  items.forEach(([key, label]) => {
    const link = el("a", "tab" + (key === active ? " is-active" : ""), label);
    link.href = hrefFor(key);
    if (key === active) link.setAttribute("aria-current", "page");
    nav.appendChild(link);
  });
  return nav;
}

function buildPriceChartPanel(data) {
  const panel = el("div", "panel");
  panel.appendChild(el("h2", null, "Price — last 6 months"));
  const wrap = el("div", "chart-wrap");
  const canvas = el("canvas", "chart");
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    `Closing price for ${data.ticker} over the last six months. Use left and right arrow keys to read individual days.`
  );
  wrap.appendChild(canvas);
  panel.appendChild(wrap);

  const history = data.history || [];
  if (history.length >= 2) {
    const closes = history.map((p) => p.close);
    const low = Math.min(...closes);
    const high = Math.max(...closes);
    const change = ((closes[closes.length - 1] - closes[0]) / closes[0]) * 100;

    const stats = el("div", "stat-line");
    stats.style.marginTop = "14px";
    [
      ["6-month low", money(low), ""],
      ["6-month high", money(high), ""],
      ["6-month change", pct(change), toneClass(change)],
    ].forEach(([label, value, cls]) => {
      const stat = el("div", "stat");
      stat.appendChild(el("span", "stat-label", label));
      stat.appendChild(el("span", "stat-value " + cls, value));
      stats.appendChild(stat);
    });
    panel.appendChild(stats);
  } else {
    panel.appendChild(el("p", "empty", data.history_error || "No price history available."));
  }
  return { panel, canvas, history };
}

function buildAnalysisNews(data) {
  const grid = el("div", "grid-2");

  const analysisPanel = el("div", "panel");
  analysisPanel.style.marginTop = "16px";
  analysisPanel.appendChild(el("h2", null, "What's going on"));
  analysisPanel.appendChild(el("p", "analysis", data.analysis || "No analysis available."));
  grid.appendChild(analysisPanel);

  const newsPanel = el("div", "panel");
  newsPanel.style.marginTop = "16px";
  newsPanel.appendChild(el("h2", null, "Recent news"));
  if (data.news && data.news.length) {
    const list = el("ul", "news-list");
    data.news.forEach((item) => {
      const li = el("li");
      const link = el("a", null, item.title);
      link.href = item.link || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      li.appendChild(link);

      // The summary is the point: it's what saves opening six tabs.
      if (item.summary) {
        li.appendChild(el("div", "news-summary", item.summary));
      }

      const meta = el("div", "meta");
      if (item.is_video) {
        meta.appendChild(el("span", "kind-tag", "Video"));
      }
      meta.appendChild(el("span", null, item.publisher || ""));
      li.appendChild(meta);
      list.appendChild(li);
    });
    newsPanel.appendChild(list);
  } else {
    newsPanel.appendChild(el("p", "empty",
      `No headlines came back from Yahoo for ${data.ticker}. That's the data source, not a quiet day.`));
  }
  grid.appendChild(newsPanel);
  return grid;
}

// The next report and how the last one went, above the history of
// reactions.
function buildEarningsFacts(data) {
  const earnings = data.earnings || {};
  const panel = el("div", "panel");
  panel.appendChild(el("h2", null, "Next report"));
  const row = el("div", "stat-line");
  const add = (label, value, cls) => {
    const stat = el("div", "stat");
    stat.appendChild(el("span", "stat-label", label));
    stat.appendChild(el("span", "stat-value " + (cls || ""), value));
    row.appendChild(stat);
  };
  add("Date", earnings.next_date
    ? formatLongDate(earnings.next_date) +
      (earnings.days_away !== null && earnings.days_away !== undefined ? `  ·  in ${earnings.days_away}d` : "")
    : "Not announced");
  if (earnings.eps_estimate !== null && earnings.eps_estimate !== undefined) {
    add("EPS estimate", num(earnings.eps_estimate));
  }
  const last = earnings.last_report;
  if (last && last.surprise_percent !== null && last.surprise_percent !== undefined) {
    add("Last quarter",
        (last.surprise_percent >= 0 ? "Beat by " : "Missed by ") + Math.abs(last.surprise_percent).toFixed(1) + "%",
        toneClass(last.surprise_percent));
  }
  const rev = data.revisions || {};
  if (rev.change_90d_percent !== null && rev.change_90d_percent !== undefined) {
    add("Next fiscal year's EPS estimate, 90d", pct(rev.change_90d_percent), toneClass(rev.change_90d_percent));
  }
  if (rev.up_30d !== null && rev.up_30d !== undefined) {
    add("Next fiscal year's revisions, 30d", `${num(rev.up_30d, 0)} up / ${num(rev.down_30d, 0)} down`);
  }
  panel.appendChild(row);
  return panel;
}

function buildFundamentalsPanel(data) {
  const quarters = data.quarters || [];
  const stats = data.stats || {};
  if (!quarters.length && !Object.keys(stats).length) return null;

  const panel = el("div", "panel");
  panel.appendChild(el("h2", null, "Fundamentals"));

  // Every figure says what it means. A number a reader can't interpret
  // isn't information, it's decoration.
  const metrics = el("div", "metrics");
  const defs = [];
  const has = (v) => v !== null && v !== undefined;

  if (stats.market_cap) {
    defs.push(["$" + bigMoney(stats.market_cap), "Company value",
               "What the whole company is worth at today's share price.", ""]);
  }
  if (stats.forward_pe) {
    defs.push([num(stats.forward_pe, 1), "Forward P/E",
               `Price divided by next fiscal year's consensus EPS: you pay $${num(stats.forward_pe, 2)} ` +
               `for each $1 analysts expect it to earn.`, ""]);
  }
  if (stats.trailing_pe) {
    defs.push([num(stats.trailing_pe, 1), "Trailing P/E",
               `You pay $${num(stats.trailing_pe, 2)} for every $1 the company earned over the past year. ` +
               `Higher means the market expects more growth — or that it's expensive.`, ""]);
  }
  if (has(stats.gross_margin_percent)) {
    defs.push([num(stats.gross_margin_percent, 1) + "%", "Gross margin",
               "Sales left after the direct cost of making what was sold -- pricing power.", ""]);
  }
  if (has(stats.operating_margin_percent)) {
    defs.push([num(stats.operating_margin_percent, 1) + "%", "Operating margin",
               "Left after running costs too (research, sales, admin) -- the business's own profitability.",
               toneClass(stats.operating_margin_percent)]);
  }
  if (has(stats.profit_margin_percent)) {
    defs.push([num(stats.profit_margin_percent, 1) + "%", "Net margin",
               `Keeps ${num(stats.profit_margin_percent, 1)} cents of every dollar of sales as profit, after all costs.`,
               toneClass(stats.profit_margin_percent)]);
  }
  if (has(stats.revenue_growth_percent)) {
    const g = stats.revenue_growth_percent;
    defs.push([num(g, 1) + "%", "Revenue growth",
               `Sales are ${g >= 0 ? "higher" : "lower"} than the same quarter a year ago.`,
               toneClass(g)]);
  }

  defs.forEach(([value, name, note, cls]) => {
    const metric = el("div", "metric");
    metric.appendChild(el("div", "metric-value " + cls, value));
    const text = el("div");
    text.appendChild(el("div", "metric-name", name));
    text.appendChild(el("div", "metric-note", note));
    metric.appendChild(text);
    metrics.appendChild(metric);
  });
  if (defs.length) panel.appendChild(metrics);
  // The same warnings as the peer table: a figure that misleads on its own
  // says so where it's shown.
  (data.flags || []).forEach((flag) => panel.appendChild(el("p", "flag-note", flag)));

  let barCanvas = null;
  if (quarters.length) {
    const label = el("p", "section-heading", "Quarterly revenue — oldest to newest");
    label.style.margin = "22px 0 4px";
    panel.appendChild(label);
    const explain = el("p", "metric-note",
      "Each bar is one three-month reporting period, in date order. Quarterly rather than " +
      "yearly because most businesses are seasonal — a December quarter often looks nothing " +
      "like a March one.");
    explain.style.margin = "0 0 10px";
    panel.appendChild(explain);
    const barWrap = el("div", "chart-wrap");
    barCanvas = el("canvas", "bar-chart");
    barCanvas.setAttribute("role", "img");
    barCanvas.setAttribute("aria-label",
      `Quarterly revenue for ${data.ticker}: ` +
      quarters.map((q) => `${periodLabel(q.period)} $${bigMoney(q.revenue)}`).join(", "));
    barWrap.appendChild(barCanvas);
    panel.appendChild(barWrap);

    const latest = quarters[quarters.length - 1];
    const yearAgo = quarters.length >= 5 ? quarters[quarters.length - 5] : null;
    if (yearAgo && yearAgo.revenue) {
      const yoy = ((latest.revenue - yearAgo.revenue) / yearAgo.revenue) * 100;
      const note = el("p", "view-sub",
        `Most recent quarter $${bigMoney(latest.revenue)}, ` +
        `${yoy >= 0 ? "up" : "down"} ${Math.abs(yoy).toFixed(1)}% from the same quarter a year earlier. ` +
        `Year-over-year rather than quarter-to-quarter, since many businesses are seasonal.`);
      note.style.margin = "12px 0 0";
      panel.appendChild(note);
    }
  }
  return { panel, barCanvas, quarters };
}

async function loadStockPeers(holder, data, token) {
  holder.replaceChildren(el("p", "loading-text", "Loading peers..."));
  const { ok, data: peers } = await api("GET", `/api/theme/${encodeURIComponent(data.theme.theme_id)}/peers`);
  if (!isCurrent(token)) return;
  if (!ok) {
    holder.replaceChildren(el("p", "empty", "Peer figures unavailable."));
    return;
  }
  const panel = el("div", "panel");
  const title = el("h2");
  title.appendChild(document.createTextNode("Against its peers in "));
  const link = el("a", "inline-link", data.theme.theme_name);
  link.href = themeHash(data.theme.theme_id) + "/peers";
  title.appendChild(link);
  panel.appendChild(title);
  panel.appendChild(buildPeerTable(peers, data.ticker));
  holder.replaceChildren(panel);
}

// Where this company stands in its theme today -- the first question the
// page answers: is this move the theme's, or the company's own?
function buildThemeContext(data) {
  const t = data.theme;
  const panel = el("div", "panel theme-context");

  if (!t) {
    panel.appendChild(el("h2", null, "Theme"));
    panel.appendChild(el("p", "form-hint",
      `${data.ticker} isn't in any of your themes, so there's no peer group to compare it with.`));
    if (DEMO) return panel;
    const add = el("button", "button-secondary", "Add to a theme");
    add.type = "button";
    add.addEventListener("click", (e) => {
      e.stopPropagation();
      openThemeMenu(add, data.ticker);
    });
    panel.appendChild(add);
    return panel;
  }

  const title = el("h2");
  title.appendChild(document.createTextNode("In theme: "));
  const link = el("a", "inline-link", t.theme_name);
  link.href = themeHash(t.theme_id);
  title.appendChild(link);
  panel.appendChild(title);
  if (t.role) panel.appendChild(el("p", "context-role", t.role));

  const own = data.price ? data.price.change_percent : null;
  const stats = el("div", "tstats");
  stats.appendChild(themeStat(`${data.ticker}, ${sessionShort()}`, pct(own), toneClass(own)));
  stats.appendChild(themeStat(`Peer median, ex-${data.ticker}`, pct(t.peer_median), toneClass(t.peer_median),
                              "Median move of the other companies in the theme -- the typical peer."));
  stats.appendChild(themeStat("vs peers", pts(t.vs_peers), toneClass(t.vs_peers)));
  stats.appendChild(themeStat(t.benchmark.ticker, pct(t.benchmark.change_percent),
                              toneClass(t.benchmark.change_percent), "The theme's benchmark ETF today."));
  stats.appendChild(themeStat(`vs ${t.benchmark.ticker}`, pts(t.vs_benchmark), toneClass(t.vs_benchmark)));
  panel.appendChild(stats);

  const verdict = el("p", "context-verdict");
  verdict.appendChild(attributionTag(t.attribution));
  const info = ATTRIBUTION[t.attribution];
  verdict.appendChild(document.createTextNode(" " + (info ? info.note
    : "Not enough peers with a price today to compare with.")));
  panel.appendChild(verdict);

  if (t.peers && t.peers.length) {
    const peers = el("div", "context-peers");
    peers.appendChild(el("span", "tstat-label", `Peers, ${sessionShort()}`));
    t.peers.forEach((p) => {
      const tag = el("a", "ticker-tag peer-tag");
      tag.href = stockHash(p.ticker);
      tag.appendChild(document.createTextNode(p.ticker + " "));
      tag.appendChild(el("span", toneClass(p.change_percent), pct(p.change_percent)));
      peers.appendChild(tag);
    });
    panel.appendChild(peers);
  }
  if (t.note) panel.appendChild(el("p", "row-note", t.note));
  return panel;
}

/* ---------------- charts ---------------- */

function drawSparkline(canvas, points) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.width / dpr || canvas.width;
  const h = canvas.height / dpr || canvas.height;

  if (canvas.width !== 88 * dpr) {
    canvas.width = 88 * dpr;
    canvas.height = 30 * dpr;
    canvas.style.width = "88px";
    canvas.style.height = "30px";
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, 88, 30);

  if (!points || points.length < 2) return;

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const stepX = 88 / (closes.length - 1);

  // Direction color is a status cue, and it always sits beside the signed
  // percentage in the row -- so meaning never depends on color alone.
  ctx.strokeStyle = closes[closes.length - 1] >= closes[0] ? COLORS.up : COLORS.down;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = "round";
  ctx.beginPath();
  closes.forEach((c, i) => {
    const x = i * stepX;
    const y = 30 - ((c - min) / range) * 24 - 3;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

const PAD = { left: 64, right: 16, top: 14, bottom: 26 };

// Pick decimal places from the span of the axis, not the price: a stock
// ranging $0.42-$0.61 needs cents, one ranging $160-$228 does not.
function axisLabel(value, range) {
  const decimals = range < 2 ? 3 : range < 20 ? 2 : range < 200 ? 1 : 0;
  return "$" + value.toLocaleString(LOCALE, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function setupChart(canvas, points) {
  state.chart = { canvas, points, hover: null };

  const redraw = () => drawPriceChart(canvas, points, state.chart.hover);
  redraw();

  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => redraw());
    ro.observe(canvas);
  } else {
    window.addEventListener("resize", redraw);
  }

  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const idx = nearestIndex(e.clientX - rect.left, rect.width, points.length);
    state.chart.hover = idx;
    drawPriceChart(canvas, points, idx);
    showTooltip(points[idx], e.clientX, e.clientY);
  });

  canvas.addEventListener("pointerleave", () => {
    state.chart.hover = null;
    drawPriceChart(canvas, points, null);
    hideTooltip();
  });

  // Keyboard equivalent of hover, so the per-point values aren't
  // mouse-only.
  canvas.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const current = state.chart.hover === null ? points.length - 1 : state.chart.hover;
    const next = Math.max(0, Math.min(points.length - 1, current + (e.key === "ArrowRight" ? 1 : -1)));
    state.chart.hover = next;
    drawPriceChart(canvas, points, next);

    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - PAD.left - PAD.right;
    const x = rect.left + PAD.left + (next / (points.length - 1)) * plotW;
    showTooltip(points[next], x, rect.top + 40);
  });

  canvas.addEventListener("blur", () => {
    state.chart.hover = null;
    drawPriceChart(canvas, points, null);
    hideTooltip();
  });
}

function nearestIndex(xCss, widthCss, count) {
  const plotW = widthCss - PAD.left - PAD.right;
  const ratio = (xCss - PAD.left) / plotW;
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
}

function drawPriceChart(canvas, points, hoverIndex) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 600;
  const cssH = canvas.clientHeight || 260;

  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const closes = points.map((p) => p.close);
  const rawMin = Math.min(...closes);
  const rawMax = Math.max(...closes);
  const pad = (rawMax - rawMin) * 0.08 || 1;
  const min = rawMin - pad;
  const max = rawMax + pad;
  const range = max - min || 1;

  const plotW = cssW - PAD.left - PAD.right;
  const plotH = cssH - PAD.top - PAD.bottom;
  const xAt = (i) => PAD.left + (i / (points.length - 1)) * plotW;
  const yAt = (v) => PAD.top + plotH - ((v - min) / range) * plotH;

  // Gridlines and y labels -- recessive, behind the data.
  ctx.font = "11px system-ui, -apple-system, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  const TICKS = 4;
  for (let i = 0; i <= TICKS; i++) {
    const value = min + (range * i) / TICKS;
    const y = yAt(value);
    ctx.strokeStyle = COLORS.gridline;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD.left, Math.round(y) + 0.5);
    ctx.lineTo(cssW - PAD.right, Math.round(y) + 0.5);
    ctx.stroke();

    ctx.fillStyle = COLORS.muted;
    ctx.fillText(axisLabel(value, range), PAD.left - 10, y);
  }

  // X labels: first, middle, last only -- never one per point.
  ctx.textBaseline = "top";
  const last = points.length - 1;
  [0, Math.floor(last / 2), last].forEach((i) => {
    ctx.fillStyle = COLORS.muted;
    ctx.textAlign = i === 0 ? "left" : i === last ? "right" : "center";
    ctx.fillText(formatDate(points[i].date), xAt(i), cssH - PAD.bottom + 8);
  });

  // Area fill (allowed for a single series) then the line on top.
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = xAt(i);
    const y = yAt(p.close);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(xAt(points.length - 1), PAD.top + plotH);
  ctx.lineTo(xAt(0), PAD.top + plotH);
  ctx.closePath();
  ctx.fillStyle = COLORS.seriesFill;
  ctx.fill();

  ctx.beginPath();
  points.forEach((p, i) => {
    const x = xAt(i);
    const y = yAt(p.close);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = COLORS.series;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.stroke();

  // Crosshair: the reader aims at a date, not at a 2px line.
  if (hoverIndex !== null && hoverIndex !== undefined) {
    const x = xAt(hoverIndex);
    const y = yAt(points[hoverIndex].close);

    ctx.strokeStyle = COLORS.axis;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, PAD.top);
    ctx.lineTo(Math.round(x) + 0.5, PAD.top + plotH);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.series;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = COLORS.surface;
    ctx.stroke();
  }
}

function showTooltip(point, clientX, clientY) {
  tooltipEl.replaceChildren();

  const value = el("div", "tip-value");
  value.appendChild(el("span", "tip-key"));
  value.appendChild(el("span", null, money(point.close)));
  tooltipEl.appendChild(value);
  tooltipEl.appendChild(el("div", "tip-label", formatDate(point.date)));

  tooltipEl.hidden = false;
  const rect = tooltipEl.getBoundingClientRect();
  let left = clientX + 14;
  if (left + rect.width > window.innerWidth - 8) left = clientX - rect.width - 14;
  tooltipEl.style.left = left + "px";
  tooltipEl.style.top = Math.max(8, clientY - rect.height - 12) + "px";
}

function hideTooltip() {
  tooltipEl.hidden = true;
}

/* ---------------- number formatting ---------------- */

function bigMoney(value) {
  if (value === null || value === undefined) return "--";
  const n = Number(value);
  const abs = Math.abs(n);
  if (abs >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return n.toFixed(0);
}

function periodLabel(iso) {
  const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 7);
  return d.toLocaleDateString(LOCALE, { month: "short", year: "numeric" });
}

function num(value, digits) {
  if (value === null || value === undefined) return "--";
  return Number(value).toFixed(digits === undefined ? 2 : digits);
}

/* ---------------- earnings calendar ---------------- */

async function showEarnings() {
  const token = beginView("earnings");
  setTitle("Earnings calendar");
  viewEl.replaceChildren(el("p", "loading-text", "Loading earnings dates..."));

  const { ok, data } = await api("GET", "/api/earnings");
  if (!isCurrent(token)) return;
  if (!ok) {
    viewEl.replaceChildren(el("p", "empty", "Could not load earnings: " + (data.error || "")));
    return;
  }

  const frag = document.createDocumentFragment();
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, "Earnings calendar"));
  frag.appendChild(head);

  const items = data.items || [];
  const unscheduled = data.unscheduled || [];

  if (!items.length) {
    frag.appendChild(
      el("p", "view-sub", "No earnings dates came back for the companies in your themes.")
    );
    frag.appendChild(
      el("p", "note",
         "This usually means the data source didn't answer rather than that nothing is scheduled. " +
         "Run `python3 tools/check_sources.py` in a terminal to see which sources are reachable.")
    );
    if (unscheduled.length) {
      frag.appendChild(el("p", "section-heading", "No date announced"));
      frag.appendChild(buildTickerRow(unscheduled));
    }
    viewEl.replaceChildren(frag);
    return;
  }

  const next = items[0];
  frag.appendChild(
    el("p", "view-sub",
       `Next up: ${next.ticker} on ${formatLongDate(next.next_date)}` +
       (next.days_away !== null && next.days_away !== undefined
         ? ` — ${next.days_away === 0 ? "today" : "in " + next.days_away + " days"}.` : "."))
  );

  // The next two weeks as a list, labelled by theme: in earnings season the
  // useful question is which themes report together, not which day a box
  // falls on.
  const soon = items.filter((i) => i.days_away !== null && i.days_away !== undefined && i.days_away <= 14);
  if (soon.length) {
    frag.appendChild(el("p", "section-heading", "Next two weeks"));
    const list = el("div", "panel upcoming");
    soon.forEach((item) => {
      const line = el("a", "upcoming-line");
      line.href = stockHash(item.ticker);
      line.appendChild(el("span", "upcoming-date", formatDate(item.next_date)));
      line.appendChild(el("span", "upcoming-ticker", item.ticker));
      line.appendChild(el("span", "upcoming-theme", item.theme || ""));
      line.appendChild(el("span", "upcoming-days",
                          item.days_away === 0 ? "today" : `in ${item.days_away}d`));
      list.appendChild(line);
    });
    frag.appendChild(list);
  }

  // Index dates -> the names reporting that day.
  const byDate = new Map();
  items.forEach((item) => {
    if (!byDate.has(item.next_date)) byDate.set(item.next_date, []);
    byDate.get(item.next_date).push(item);
  });

  const today = data.today ? new Date(data.today + "T00:00:00") : new Date();
  const months = el("div", "calendars");
  for (let offset = 0; offset < 3; offset++) {
    months.appendChild(
      buildMonth(today.getFullYear(), today.getMonth() + offset, byDate, data.today)
    );
  }
  frag.appendChild(months);

  // Anything past the three rendered months still needs somewhere to live.
  const lastRendered = new Date(today.getFullYear(), today.getMonth() + 3, 0);
  const beyond = items.filter((i) => new Date(i.next_date + "T00:00:00") > lastRendered);
  if (beyond.length) {
    frag.appendChild(el("p", "section-heading", "Further out"));
    const list = el("ul", "plain-list");
    beyond.forEach((item) => {
      const li = el("li");
      const btn = el("button", "link-button", `${item.ticker} — ${formatLongDate(item.next_date)}`);
      btn.type = "button";
      btn.addEventListener("click", () => go(stockHash(item.ticker)));
      li.appendChild(btn);
      list.appendChild(li);
    });
    frag.appendChild(list);
  }

  if (unscheduled.length) {
    frag.appendChild(el("p", "section-heading", "No date announced yet"));
    frag.appendChild(buildTickerRow(unscheduled));
  }

  viewEl.replaceChildren(frag);
}

function buildTickerRow(tickers) {
  const wrap = el("div", "theme-tickers");
  tickers.forEach((t) => {
    const tag = el("button", "ticker-tag", t);
    tag.type = "button";
    tag.addEventListener("click", () => go(stockHash(t)));
    wrap.appendChild(tag);
  });
  return wrap;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function buildMonth(year, monthIndex, byDate, todayIso) {
  const first = new Date(year, monthIndex, 1);
  const monthName = first.toLocaleDateString(LOCALE, { month: "long", year: "numeric" });

  const cal = el("div", "calendar");
  cal.appendChild(el("h3", "calendar-title", monthName));

  const grid = el("div", "calendar-grid");
  WEEKDAYS.forEach((d) => grid.appendChild(el("div", "weekday", d)));

  // Blank cells so the 1st lands on the right weekday.
  for (let i = 0; i < first.getDay(); i++) grid.appendChild(el("div", "day is-blank"));

  const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
  for (let day = 1; day <= daysInMonth; day++) {
    const date = new Date(year, monthIndex, day);
    const iso = `${year}-${String(monthIndex + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cell = el("div", "day");
    if (date.getDay() === 0 || date.getDay() === 6) cell.classList.add("is-weekend");
    if (iso === todayIso) cell.classList.add("is-today");

    cell.appendChild(el("span", "day-number", String(day)));

    const reporting = byDate.get(iso);
    if (reporting) {
      cell.classList.add("has-events");
      reporting.forEach((item) => {
        const tag = el("button", "day-ticker", item.ticker);
        tag.type = "button";
        tag.title = `${item.ticker} reports ${formatLongDate(item.next_date)}`;
        tag.addEventListener("click", () => go(stockHash(item.ticker)));
        cell.appendChild(tag);
      });
    }
    grid.appendChild(cell);
  }

  cal.appendChild(grid);
  return cal;
}

/* ---------------- earnings setup ---------------- */

function buildSetupPanel(setup, ticker, daysAway) {
  if (!setup || !setup.reactions || setup.reactions.length < 3) return null;

  const panel = el("div", "panel");
  panel.appendChild(el("h2", null, "Going into earnings"));

  // Lead with the abnormal figure when there's a model for enough reports:
  // a raw move includes whatever the whole market did that session.
  const modelled = (setup.modelled_count || 0) >= 3 && setup.median_abs_abnormal !== null
                   && setup.median_abs_abnormal !== undefined;
  const lead = el("p", "setup-lead");
  if (modelled) {
    lead.appendChild(el("span", "setup-figure", "\u00b1" + num(setup.median_abs_abnormal, 1) + "%"));
    lead.appendChild(el("span", null,
      ` typical abnormal move after ${ticker} reports -- the part the market that day doesn't ` +
      `explain -- across ${setup.modelled_count} reports. The raw move was ` +
      `\u00b1${num(setup.median_abs_move, 1)}%.`));
  } else {
    lead.appendChild(el("span", "setup-figure", "\u00b1" + num(setup.median_abs_move, 1) + "%"));
    lead.appendChild(el("span", null,
      ` typical move the session after ${ticker} reports, across its last ` +
      `${setup.reactions.length} reports.`));
  }
  panel.appendChild(lead);

  // The finding worth leading with, when it applies: beating estimates
  // has not meant the stock did better than expected. Markets price the
  // expectation, not the analyst number.
  if (modelled && setup.beat_count >= 3 && setup.beat_but_lagged > 0) {
    const share = setup.beat_but_lagged / setup.beat_count;
    const note = el("p", "setup-note" + (share >= 0.4 ? " is-striking" : ""));
    note.textContent =
      `Beat the estimate in ${setup.beat_count} of its reports -- and still lagged what its ` +
      `market model expected the next session ${setup.beat_but_lagged} ` +
      `time${setup.beat_but_lagged === 1 ? "" : "s"} (in raw terms it fell ${setup.beat_but_fell}). ` +
      (share >= 0.4
        ? "For this stock, beating has not reliably meant outperforming: what matters is the "
          + "result against what was already priced in, not against the analyst figure."
        : "");
    panel.appendChild(note);
    if (setup.unusual_count) {
      panel.appendChild(el("p", "metric-note",
        `${setup.unusual_count} of those reactions were more than two standard deviations beyond ` +
        `${ticker}'s ordinary daily moves -- genuinely unusual, not just a volatile stock being volatile.`));
    }
  } else if (setup.beat_count >= 3 && setup.beat_but_fell > 0) {
    const share = setup.beat_but_fell / setup.beat_count;
    const note = el("p", "setup-note" + (share >= 0.4 ? " is-striking" : ""));
    note.textContent =
      `Beat the estimate in ${setup.beat_count} of those reports — and still fell the next ` +
      `session ${setup.beat_but_fell} time${setup.beat_but_fell === 1 ? "" : "s"}. ` +
      (share >= 0.4
        ? "For this stock, beating has not reliably meant rising: what matters is the result "
          + "against what was already priced in, not against the analyst figure."
        : "");
    panel.appendChild(note);
  }

  const wrap = el("div", "chart-wrap");
  const canvas = el("canvas", "reaction-chart");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label",
    "Abnormal move the session after each past earnings report: " +
    setup.reactions.map((r) => {
      const v = reactionValue(r);
      return `${r.date} ${v > 0 ? "up" : "down"} ${Math.abs(v)} percent` +
        (r.abnormal_move === null || r.abnormal_move === undefined ? " (raw, no model)" : "");
    }).join(", "));
  wrap.appendChild(canvas);
  panel.appendChild(wrap);

  const legend = el("p", "metric-note");
  legend.textContent =
    "Each bar is one past report: the abnormal return on the first session that could react " +
    "-- the next day after an after-close report, the same day after a before-open one. " +
    "Abnormal means the stock's move minus what its market model predicted given SPY that " +
    "session (beta estimated over the 120 sessions ending two weeks before the report). Grey " +
    "bars had too little earlier history for a model and show the raw move. Hover a bar for " +
    "the prices, SPY's move and the run-up into the report. This is what happened, not what will.";
  legend.style.margin = "10px 0 0";
  panel.appendChild(legend);

  const trend = setup.estimate_trend;
  if (trend && (trend.current || trend.days_90)) {
    const stats = el("div", "stat-line");
    stats.style.marginTop = "16px";
    if (trend.current && trend.days_90) {
      const shift = ((trend.current - trend.days_90) / Math.abs(trend.days_90)) * 100;
      const stat = el("div", "stat");
      stat.appendChild(el("span", "stat-label", "Coming quarter's EPS estimate, 90d"));
      stat.appendChild(el("span", "stat-value " + toneClass(shift),
        (shift >= 0 ? "+" : "") + num(shift, 0) + "%"));
      stats.appendChild(stat);
    }
    if (trend.up_last_30_days !== null && trend.up_last_30_days !== undefined) {
      const stat = el("div", "stat");
      stat.appendChild(el("span", "stat-label", "Coming quarter's revisions, 30d"));
      stat.appendChild(el("span", "stat-value",
        `${num(trend.up_last_30_days, 0)} up / ${num(trend.down_last_30_days, 0)} down`));
      stats.appendChild(stat);
    }
    panel.appendChild(stats);
  }

  return { panel, canvas, reactions: setup.reactions };
}

const REACT_PAD = { left: 8, right: 8, top: 22, bottom: 30 };

function attachReactionHover(canvas, reactions) {
  const points = reactions.slice().reverse();

  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - REACT_PAD.left - REACT_PAD.right;
    const slot = plotW / points.length;
    const idx = Math.floor((e.clientX - rect.left - REACT_PAD.left) / slot);
    if (idx < 0 || idx >= points.length) {
      hideTooltip();
      return;
    }
    showReactionTooltip(points[idx], e.clientX, e.clientY);
  });

  canvas.addEventListener("pointerleave", hideTooltip);
}

// The abnormal move where a market model exists, the raw move otherwise.
function reactionValue(r) {
  return r.abnormal_move !== null && r.abnormal_move !== undefined ? r.abnormal_move : r.next_session_move;
}

function showReactionTooltip(reaction, clientX, clientY) {
  tooltipEl.replaceChildren();

  const hasModel = reaction.abnormal_move !== null && reaction.abnormal_move !== undefined;
  const value = el("div", "tip-value " + toneClass(reactionValue(reaction)));
  value.textContent = (hasModel ? "Abnormal " : "Raw ") + (reactionValue(reaction) >= 0 ? "+" : "") +
    num(reactionValue(reaction), 2) + "%" +
    (hasModel && reaction.standardized !== null ? `  (${num(reaction.standardized, 1)} sd)` : "");
  tooltipEl.appendChild(value);
  if (hasModel) {
    tooltipEl.appendChild(el("div", "tip-label",
      `Raw ${pct(reaction.next_session_move)} = expected ${pct(reaction.expected_move)} ` +
      `(SPY ${pct(reaction.market_move)}, beta ${num(reaction.beta, 2)}) + abnormal ${pct(reaction.abnormal_move)}`));
    if (reaction.runup_abnormal !== null && reaction.runup_abnormal !== undefined) {
      tooltipEl.appendChild(el("div", "tip-label",
        `20 sessions before: ${pct(reaction.runup_abnormal)} beyond its model`));
    }
  }

  // The comparison spelled out, because a percentage with no stated
  // endpoints is a number the reader has to take on faith.
  if (reaction.from_close && reaction.to_close) {
    tooltipEl.appendChild(el("div", "tip-label",
      `${money(reaction.from_close)} \u2192 ${money(reaction.to_close)}`));
  }
  tooltipEl.appendChild(el("div", "tip-label",
    `Reported ${formatLongDate(reaction.date)}` +
    (reaction.timing ? `, ${reaction.timing}` : "")));
  if (reaction.surprise_percent !== null && reaction.surprise_percent !== undefined) {
    tooltipEl.appendChild(el("div", "tip-label",
      `EPS ${reaction.surprise_percent >= 0 ? "beat" : "missed"} by ` +
      `${Math.abs(reaction.surprise_percent).toFixed(1)}%`));
  }

  tooltipEl.hidden = false;
  const rect = tooltipEl.getBoundingClientRect();
  let left = clientX + 14;
  if (left + rect.width > window.innerWidth - 8) left = clientX - rect.width - 14;
  tooltipEl.style.left = left + "px";
  tooltipEl.style.top = Math.max(8, clientY - rect.height - 12) + "px";
}

function drawReactionChart(canvas, reactions) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 520;
  const cssH = canvas.clientHeight || 170;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if (!reactions.length) return;

  // Oldest on the left, so it reads like time.
  const points = reactions.slice().reverse();
  const values = points.map(reactionValue);
  const extent = Math.max(...values.map(Math.abs)) || 1;

  const plotW = cssW - REACT_PAD.left - REACT_PAD.right;
  const plotH = cssH - REACT_PAD.top - REACT_PAD.bottom;
  const zeroY = REACT_PAD.top + plotH / 2;

  ctx.strokeStyle = COLORS.axis;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(REACT_PAD.left, Math.round(zeroY) + 0.5);
  ctx.lineTo(cssW - REACT_PAD.right, Math.round(zeroY) + 0.5);
  ctx.stroke();

  const slot = plotW / points.length;
  const barW = Math.max(12, Math.min(46, slot - 12));

  ctx.font = "10.5px system-ui, -apple-system, sans-serif";
  ctx.textAlign = "center";

  points.forEach((r, i) => {
    const value = reactionValue(r);
    const modelled = r.abnormal_move !== null && r.abnormal_move !== undefined;
    const x = REACT_PAD.left + slot * i + (slot - barW) / 2;
    const h = Math.max(2, (Math.abs(value) / extent) * (plotH / 2 - 4));
    const up = value >= 0;
    const y = up ? zeroY - h : zeroY;

    // Unmodelled reactions in grey: a raw move drawn in the same colours
    // would pass for an abnormal one.
    ctx.fillStyle = modelled ? (up ? COLORS.up : COLORS.down) : COLORS.axis;
    roundedTopRect(ctx, x, up ? y : zeroY, barW, h, 3);
    if (!up) {
      // Mirror the rounding so the data-end is the one away from zero.
      ctx.save();
      ctx.translate(0, zeroY * 2 + h);
      ctx.scale(1, -1);
      ctx.beginPath();
      roundedTopRect(ctx, x, zeroY, barW, h, 3);
      ctx.fill();
      ctx.restore();
    } else {
      ctx.fill();
    }

    ctx.fillStyle = modelled ? (up ? COLORS.up : COLORS.down) : COLORS.muted;
    ctx.textBaseline = up ? "bottom" : "top";
    ctx.fillText((value >= 0 ? "+" : "") + value.toFixed(1) + "%",
                 x + barW / 2, up ? y - 4 : zeroY + h + 4);

    ctx.fillStyle = COLORS.muted;
    ctx.textBaseline = "top";
    ctx.fillText(String(r.date).slice(0, 7), x + barW / 2, cssH - REACT_PAD.bottom + 14);
  });
}

/* ---------------- quarterly revenue chart ---------------- */

const BAR_PAD = { left: 10, right: 10, top: 26, bottom: 30 };

function drawQuarterlyBars(canvas, quarters, hoverIndex) {
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 520;
  const cssH = canvas.clientHeight || 190;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if (!quarters.length) return;

  const values = quarters.map((q) => q.revenue);
  const max = Math.max(...values) || 1;
  const plotW = cssW - BAR_PAD.left - BAR_PAD.right;
  const plotH = cssH - BAR_PAD.top - BAR_PAD.bottom;
  const baseline = BAR_PAD.top + plotH;

  // 2px gap between bars, per the mark spec -- adjacent fills need a
  // surface-coloured gutter or they read as one block.
  const slot = plotW / quarters.length;
  const barW = Math.max(10, slot - 10);

  ctx.strokeStyle = COLORS.axis;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(BAR_PAD.left, Math.round(baseline) + 0.5);
  ctx.lineTo(cssW - BAR_PAD.right, Math.round(baseline) + 0.5);
  ctx.stroke();

  ctx.font = "11px system-ui, -apple-system, sans-serif";
  ctx.textAlign = "center";

  quarters.forEach((q, i) => {
    const x = BAR_PAD.left + slot * i + (slot - barW) / 2;
    const h = Math.max(2, (q.revenue / max) * plotH);
    const y = baseline - h;

    ctx.fillStyle = hoverIndex === i ? COLORS.series : COLORS.seriesBar;
    roundedTopRect(ctx, x, y, barW, h, 4);
    ctx.fill();

    ctx.fillStyle = COLORS.muted;
    ctx.textBaseline = "bottom";
    ctx.fillText("$" + bigMoney(q.revenue), x + barW / 2, y - 6);

    ctx.textBaseline = "top";
    ctx.fillText(periodLabel(q.period), x + barW / 2, baseline + 8);
  });
}

function roundedTopRect(ctx, x, y, w, h, r) {
  const radius = Math.min(r, w / 2, h);
  ctx.beginPath();
  ctx.moveTo(x, y + h);
  ctx.lineTo(x, y + radius);
  ctx.quadraticCurveTo(x, y, x + radius, y);
  ctx.lineTo(x + w - radius, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
  ctx.lineTo(x + w, y + h);
  ctx.closePath();
}

function setupBarChart(canvas, quarters) {
  const redraw = (hover) => drawQuarterlyBars(canvas, quarters, hover);
  redraw(null);

  if (window.ResizeObserver) {
    new ResizeObserver(() => redraw(null)).observe(canvas);
  }

  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - BAR_PAD.left - BAR_PAD.right;
    const slot = plotW / quarters.length;
    const idx = Math.floor((e.clientX - rect.left - BAR_PAD.left) / slot);
    if (idx < 0 || idx >= quarters.length) {
      redraw(null);
      hideTooltip();
      return;
    }
    redraw(idx);
    showQuarterTooltip(quarters[idx], e.clientX, e.clientY);
  });

  canvas.addEventListener("pointerleave", () => {
    redraw(null);
    hideTooltip();
  });
}

function showQuarterTooltip(q, clientX, clientY) {
  tooltipEl.replaceChildren();
  const value = el("div", "tip-value");
  value.appendChild(el("span", "tip-key"));
  value.appendChild(el("span", null, "$" + bigMoney(q.revenue)));
  tooltipEl.appendChild(value);
  tooltipEl.appendChild(el("div", "tip-label", "Revenue · " + periodLabel(q.period)));
  if (q.net_income !== null && q.net_income !== undefined) {
    tooltipEl.appendChild(
      el("div", "tip-label", `Net income $${bigMoney(q.net_income)}` +
         (q.net_margin !== null && q.net_margin !== undefined ? ` (${num(q.net_margin, 1)}% margin)` : ""))
    );
  }
  tooltipEl.hidden = false;
  const rect = tooltipEl.getBoundingClientRect();
  let left = clientX + 14;
  if (left + rect.width > window.innerWidth - 8) left = clientX - rect.width - 14;
  tooltipEl.style.left = left + "px";
  tooltipEl.style.top = Math.max(8, clientY - rect.height - 12) + "px";
}

/* ---------------- ask (the agent, in the browser) ---------------- */

const STARTERS = DEMO && DEMO.chat && DEMO.chat.length
  ? DEMO.chat.map((c) => c.question)
  : [
      "Which of my stocks reports soonest, and how did they do last quarter?",
      "What moved most in the market today that isn't on my watchlist?",
      "Compare the profit margins of the companies in my Memory & storage theme.",
    ];

async function showChat() {
  beginView("ask");
  setTitle("Ask");

  const frag = document.createDocumentFragment();
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, "Ask"));
  frag.appendChild(head);
  frag.appendChild(
    el("p", "view-sub",
       "The same agent that runs in the terminal. It picks its own tools — you'll see every " +
       "lookup it makes before it answers.")
  );

  const log = el("div", "chat-log");
  log.id = "chat-log";
  frag.appendChild(log);

  const form = el("form", "chat-form");
  const input = el("input", "chat-input");
  input.type = "text";
  input.id = "chat-input";
  input.placeholder = "Ask about your themes or the market";
  input.autocomplete = "off";
  const send = el("button", "chat-send", "Ask");
  send.type = "submit";
  form.appendChild(input);
  form.appendChild(send);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q || state.chatBusy) return;
    input.value = "";
    askAgent(q);
  });
  frag.appendChild(form);

  viewEl.replaceChildren(frag);
  renderChat();
  input.focus();
}

function renderChat() {
  const log = document.getElementById("chat-log");
  if (!log) return;
  log.replaceChildren();

  if (!state.chat.length) {
    const empty = el("div", "chat-empty");
    empty.appendChild(el("p", "chat-empty-title", DEMO
      ? "Recorded when the snapshot was taken -- pick one to replay it"
      : "Try one of these"));
    STARTERS.forEach((q) => {
      const btn = el("button", "starter", q);
      btn.type = "button";
      btn.addEventListener("click", () => askAgent(q));
      empty.appendChild(btn);
    });
    log.appendChild(empty);
    return;
  }

  state.chat.forEach((turn) => {
    if (turn.role === "user") {
      log.appendChild(el("div", "bubble user", turn.content));
      return;
    }

    const wrap = el("div", "assistant-turn");
    // The tool calls stay visible on purpose: the whole point of an agent
    // is that it decided what to look up, and hiding that turns a
    // legible chain of reasoning into a black box.
    if (turn.trace && turn.trace.length) {
      const steps = el("details", "trace");
      const summary = el("summary", null,
        `${turn.trace.length} lookup${turn.trace.length === 1 ? "" : "s"}`);
      steps.appendChild(summary);
      turn.trace.forEach((call) => {
        const args = Object.entries(call.input || {})
          .map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
        steps.appendChild(el("div", "trace-call", `${call.tool}(${args})`));
      });
      wrap.appendChild(steps);
    }
    wrap.appendChild(el("div", "bubble agent" + (turn.error ? " is-error" : ""), turn.content));
    log.appendChild(wrap);
  });

  if (state.chatBusy) {
    log.appendChild(el("div", "bubble agent thinking", "Looking things up..."));
  }
  log.scrollTop = log.scrollHeight;
}

async function askAgent(question) {
  if (DEMO) return replayAgent(question);
  state.chat.push({ role: "user", content: question });
  state.chatBusy = true;
  renderChat();

  // Only text turns go back, matching what the server will replay.
  const history = state.chat
    .filter((t) => !t.error)
    .slice(0, -1)
    .map((t) => ({ role: t.role, content: t.content }));

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, history }),
    });
    const data = await res.json();
    state.chat.push(
      data.error
        ? { role: "assistant", content: data.error, trace: data.trace || [], error: true }
        : { role: "assistant", content: data.answer, trace: data.trace || [] }
    );
  } catch (err) {
    state.chat.push({ role: "assistant", content: String(err), trace: [], error: true });
  } finally {
    state.chatBusy = false;
    renderChat();
  }
}

// The demo can't call the model. It replays the conversations recorded
// when the snapshot was taken -- real answers, with their real lookups.
function replayAgent(question) {
  state.chat.push({ role: "user", content: question });
  const recorded = (DEMO.chat || []).find((c) => c.question === question);
  state.chat.push(recorded
    ? { role: "assistant", content: recorded.answer, trace: recorded.trace || [] }
    : { role: "assistant", trace: [], content: "This demo replays conversations recorded when the snapshot " +
        "was taken, so it can only answer the suggested questions. Run Market Agent locally with your own " +
        "API key to ask anything." });
  renderChat();
}

/* ---------------- daily brief ---------------- */

function buildBriefPanel() {
  const panel = el("div", "brief");

  const head = el("div", "brief-head");
  head.appendChild(el("h2", null, "AI brief"));
  const refresh = el("button", "brief-refresh", "Refresh");
  refresh.type = "button";
  refresh.addEventListener("click", () => loadBrief(panel, true));
  head.appendChild(refresh);
  panel.appendChild(head);

  panel.appendChild(el("div", "brief-body", "Reading your themes..."));
  return panel;
}

async function loadBrief(panel, force) {
  const body = panel.querySelector(".brief-body");
  body.replaceChildren(el("p", null, force ? "Rewriting..." : "Reading your themes..."));

  const { ok, data } = await api("GET", "/api/brief" + (force && !DEMO ? "?t=" + Date.now() : ""));
  if (!ok) {
    body.replaceChildren(el("p", null, "Brief unavailable: " + (data.error || "")));
    return;
  }

  body.replaceChildren();
  String(data.brief || "")
    .split(/\n\s*\n/)
    .filter((para) => para.trim())
    .forEach((para) => body.appendChild(el("p", null, para.trim())));

  const old = panel.querySelector(".brief-meta");
  if (old) old.remove();
  if (data.generated_at) {
    panel.appendChild(el("p", "brief-meta", DEMO
      ? `Written ${data.generated_at} when the snapshot was taken, from the data below. Not financial advice.`
      : `Written ${data.generated_at} from the data below. Not financial advice.`));
  }
}

/* ---------------- discover ---------------- */

async function showDiscover() {
  const token = beginView("discover");
  setTitle("Discover");
  viewEl.replaceChildren(el("p", "loading-text", "Scanning the market..."));

  const { ok, data } = await api("GET", "/api/discover");
  if (!isCurrent(token)) return;
  if (!ok) {
    viewEl.replaceChildren(el("p", "empty", "Discover failed: " + (data.error || "")));
    return;
  }

  const frag = document.createDocumentFragment();
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, "Discover"));
  frag.appendChild(head);
  frag.appendChild(
    el("p", "view-sub", "What's moving across the market today that isn't in your themes. " +
       "Use + to add a company to one.")
  );

  const scanned = data.scanned || 0;
  frag.appendChild(
    el(
      "p",
      "note",
      data.source === "fallback"
        ? `The market scanner didn't respond, so this is a fixed list of ${scanned} large caps instead of a live market scan. Not a recommendation to buy anything.`
        : `Yahoo ranked the whole US market and returned the top ${scanned}: biggest gainers, biggest losers, and unusually active — ` +
          `all above $2B in value and $5 a share. This reports what happened, not what to buy.`
    )
  );

  // Themes first: the pattern across names is usually more informative
  // than any single row.
  const themes = data.themes || [];
  if (themes.length) {
    const wrap = el("div", "themes");
    themes.forEach((t) => {
      const card = el("div", "theme-card");
      card.appendChild(el("h3", null, t.theme));
      card.appendChild(el("p", "theme-what", t.what));
      if (t.tickers && t.tickers.length) {
        const tags = el("div", "theme-tickers");
        t.tickers.forEach((sym) => {
          const tag = el("button", "ticker-tag", sym);
          tag.type = "button";
          tag.addEventListener("click", () => go(stockHash(sym)));
          tags.appendChild(tag);
        });
        card.appendChild(tags);
      }
      wrap.appendChild(card);
    });
    frag.appendChild(el("p", "section-heading", "Themes today"));
    frag.appendChild(wrap);
  }

  const rows = data.rows || [];
  if (!rows.length) {
    frag.appendChild(el("p", "empty", "Nothing unusual surfaced today."));
    viewEl.replaceChildren(frag);
    return;
  }

  frag.appendChild(el("p", "section-heading", "Biggest moves outside your themes"));
  const list = el("div", "rows");
  rows.forEach((row) => list.appendChild(buildRow(row, { discover: true })));
  frag.appendChild(list);

  const headlines = data.market_headlines || [];
  if (headlines.length) {
    frag.appendChild(el("p", "section-heading", "Across the market"));
    const panel = el("div", "panel");
    panel.style.marginTop = "0";
    const ul = el("ul", "news-list");
    headlines.forEach((h) => {
      const li = el("li");
      const a = el("a", null, h.title);
      a.href = h.link || "#";
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.appendChild(a);
      li.appendChild(el("div", "meta", h.publisher || ""));
      ul.appendChild(li);
    });
    panel.appendChild(ul);
    frag.appendChild(panel);
  }

  viewEl.replaceChildren(frag);

  rows.forEach((row) => {
    const canvas = list.querySelector(`canvas[data-ticker="${cssEscape(row.ticker)}"]`);
    if (canvas) drawSparkline(canvas, row.history || []);
  });
}

/* ---------------- search ---------------- */

async function showSearch(query) {
  const token = beginView("search", null);
  setTitle("Search");
  viewEl.replaceChildren(el("p", "loading-text", `Searching for ${query}...`));

  const { ok, data } = await api("GET", `/api/search?q=${encodeURIComponent(query)}`);
  if (!isCurrent(token)) return;
  if (!ok) {
    viewEl.replaceChildren(el("p", "empty", "Search failed: " + (data.error || "")));
    return;
  }

  const frag = document.createDocumentFragment();
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, "Search"));
  frag.appendChild(head);

  if (!data.results || !data.results.length) {
    frag.appendChild(el("p", "empty", data.message || "No results."));
    viewEl.replaceChildren(frag);
    return;
  }

  frag.appendChild(el("p", "view-sub", "Click to open, or add it to one of your themes."));

  const list = el("div", "rows");
  data.results.forEach((result) => {
    const row = el("button", "row level-quiet");
    row.type = "button";

    const left = el("div");
    left.appendChild(el("div", "ticker", result.ticker));
    row.appendChild(left);

    row.appendChild(el("div", "headline", "Open full analysis"));
    row.appendChild(el("div", "price", money(result.price)));
    row.appendChild(el("div", "delta " + toneClass(result.change_percent), pct(result.change_percent)));
    row.appendChild(el("div"));

    const owner = state.themes.find((t) => t.stocks.some((s) => s.ticker === result.ticker));
    if (owner) {
      row.appendChild(el("span", "attr-tag attr-none", "In " + owner.name));
    } else if (DEMO) {
      row.appendChild(el("div"));
    } else {
      const add = el("button", "remove", "+");
      add.type = "button";
      add.title = `Add ${result.ticker} to a theme`;
      add.setAttribute("aria-label", `Add ${result.ticker} to a theme`);
      add.addEventListener("click", (e) => {
        e.stopPropagation();
        openThemeMenu(add, result.ticker);
      });
      row.appendChild(add);
    }

    row.addEventListener("click", () => go(stockHash(result.ticker)));
    list.appendChild(row);
  });

  frag.appendChild(list);
  viewEl.replaceChildren(frag);
}

/* ---------------- wiring ---------------- */

document.getElementById("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("search-input");
  const query = input.value.trim().toUpperCase();
  if (!query) return;
  input.value = "";
  go("#/search/" + encodeURIComponent(query));
});

window.addEventListener("hashchange", route);

// The sidebar and add-to-theme menus need the theme setup, and the pages
// need to know which session the prices are from, so both load before the
// first page draws.
if (DEMO) document.querySelector(".main").prepend(buildDemoBanner());
Promise.all([loadOverview(), loadThemes()]).then(route);
