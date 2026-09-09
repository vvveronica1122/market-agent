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
  up: "#0F7B36",
  down: "#B3261E",
  gridline: "#EEDFD8",
  axis: "#D6C3BC",
  muted: "#8A7278",
  surface: "#FFFBF9",
};

const state = { view: "watchlist", rows: [], chart: null };

const viewEl = document.getElementById("view");
const stripEl = document.getElementById("market-strip");
const tooltipEl = document.getElementById("tooltip");

/* ---------------- helpers ---------------- */

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
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function setActiveNav(view) {
  document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === view);
  });
}

/* ---------------- market strip ---------------- */

async function loadOverview() {
  try {
    const res = await fetch("/api/overview");
    const data = await res.json();
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
  session.appendChild(el("span", null, data.market ? `${data.market.state} · ${data.market.time}` : ""));
  frag.appendChild(session);

  stripEl.replaceChildren(frag);
}

/* ---------------- watchlist ---------------- */

async function showWatchlist(filterMovers) {
  state.view = filterMovers ? "movers" : "watchlist";
  setActiveNav(state.view);

  viewEl.replaceChildren(el("p", "loading-text", "Loading your watchlist..."));

  let data;
  try {
    const res = await fetch("/api/watchlist/data");
    data = await res.json();
  } catch (err) {
    viewEl.replaceChildren(el("p", "empty", "Could not load watchlist: " + err));
    return;
  }

  state.rows = data.rows || [];
  let rows = state.rows;
  if (filterMovers) {
    rows = rows.filter((r) => r.price && Math.abs(r.price.change_percent || 0) >= 1);
  }

  const frag = document.createDocumentFragment();

  const head = el("div", "view-head");
  head.appendChild(el("h1", null, filterMovers ? "Today's Movers" : "Watchlist"));
  frag.appendChild(head);

  const marketPct = data.market_change_percent;
  frag.appendChild(
    el(
      "p",
      "view-sub",
      filterMovers
        ? "Names on your list that moved at least 1% today."
        : "Sorted by what needs attention today, not alphabetically." +
            (marketPct !== null && marketPct !== undefined ? `  Market (SPY) ${pct(marketPct)}.` : "")
    )
  );

  if (!rows.length) {
    frag.appendChild(
      el("p", "empty", filterMovers ? "Nothing moved much today." : "Your watchlist is empty. Add a ticker on the left.")
    );
    viewEl.replaceChildren(frag);
    return;
  }

  // The brief loads separately so a slow Claude call never delays the
  // list -- the numbers are the urgent part.
  let briefPanel = null;
  if (!filterMovers) {
    briefPanel = buildBriefPanel();
    frag.appendChild(briefPanel);
  }

  const list = el("div", "rows");
  rows.forEach((row) => list.appendChild(buildRow(row)));
  frag.appendChild(list);
  viewEl.replaceChildren(frag);

  if (briefPanel) loadBrief(briefPanel, false);

  // Sparklines must be drawn after the canvases are in the document,
  // otherwise clientWidth is 0 and nothing renders.
  rows.forEach((row) => {
    const canvas = list.querySelector(`canvas[data-ticker="${cssEscape(row.ticker)}"]`);
    if (canvas) drawSparkline(canvas, row.history || []);
  });
}

function cssEscape(value) {
  return String(value).replace(/["\\]/g, "\\$&");
}

function buildRow(row, opts) {
  const discover = !!(opts && opts.discover);
  const level = row.attention ? row.attention.level : "quiet";
  const button = el("button", `row level-${level}` + (discover ? " is-discover" : ""));
  button.type = "button";

  const left = el("div");
  left.appendChild(el("div", "ticker", row.ticker));
  const tagText = discover
    ? "Not on your list"
    : level === "high" ? "Needs attention" : level === "medium" ? "Worth a look" : "Quiet";
  left.appendChild(el("span", "attention-tag", tagText));
  button.appendChild(left);

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
  button.appendChild(middle);

  button.appendChild(el("div", "price", row.price ? money(row.price.price) : "--"));

  const delta = el(
    "div",
    "delta " + (row.price ? toneClass(row.price.change_percent) : ""),
    row.price ? pct(row.price.change_percent) : "--"
  );
  button.appendChild(delta);

  const sparkCell = el("div", "spark-cell");
  const canvas = el("canvas", "spark");
  canvas.dataset.ticker = row.ticker;
  canvas.width = 88;
  canvas.height = 30;
  sparkCell.appendChild(canvas);
  sparkCell.appendChild(el("span", "spark-label", "1 month"));
  button.appendChild(sparkCell);

  if (discover) {
    const add = el("button", "add", "+");
    add.type = "button";
    add.title = `Add ${row.ticker} to watchlist`;
    add.addEventListener("click", (e) => {
      e.stopPropagation();
      addTicker(row.ticker);
    });
    button.appendChild(add);
  } else {
    const remove = el("button", "remove", "×");
    remove.type = "button";
    remove.title = `Remove ${row.ticker}`;
    remove.addEventListener("click", (e) => {
      e.stopPropagation();
      removeTicker(row.ticker);
    });
    button.appendChild(remove);
  }

  button.addEventListener("click", () => showDetail(row.ticker));
  return button;
}

/* ---------------- detail ---------------- */

async function showDetail(ticker) {
  state.view = "detail";
  setActiveNav(null);
  viewEl.replaceChildren(el("p", "loading-text", `Loading ${ticker}...`));

  let data;
  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}`);
    data = await res.json();
  } catch (err) {
    viewEl.replaceChildren(el("p", "empty", "Could not load " + ticker + ": " + err));
    return;
  }

  const frag = document.createDocumentFragment();

  const back = el("button", "back", "← Back to watchlist");
  back.type = "button";
  back.addEventListener("click", () => showWatchlist(false));
  frag.appendChild(back);

  const head = el("div", "detail-head");
  head.appendChild(el("h1", null, data.ticker));
  if (data.price) {
    head.appendChild(el("div", "detail-price", money(data.price.price)));
    head.appendChild(
      el("div", "detail-delta " + toneClass(data.price.change_percent),
         `${pct(data.price.change_percent)} today`)
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
        `SPY ${pct(data.market.change_percent)} today — ${data.ticker} is ${
          rel >= 0 ? "outperforming" : "underperforming"
        } the market by ${Math.abs(rel).toFixed(2)} points.`
      )
    );
  }

  // Chart panel
  const chartPanel = el("div", "panel");
  chartPanel.appendChild(el("h2", null, "Price — last 6 months"));
  const wrap = el("div", "chart-wrap");
  const canvas = el("canvas", "chart");
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    `Closing price for ${data.ticker} over the last six months. Use left and right arrow keys to read individual days.`
  );
  wrap.appendChild(canvas);
  chartPanel.appendChild(wrap);

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
    chartPanel.appendChild(stats);
  } else {
    chartPanel.appendChild(el("p", "empty", data.history_error || "No price history available."));
  }
  frag.appendChild(chartPanel);

  // Analysis + news side by side
  const grid = el("div", "grid-2");

  const analysisPanel = el("div", "panel");
  analysisPanel.style.marginTop = "0";
  analysisPanel.appendChild(el("h2", null, "What's going on"));
  analysisPanel.appendChild(el("p", "analysis", data.analysis || "No analysis available."));
  if (data.events && data.events.next_earnings_date) {
    const stat = el("div", "stat");
    stat.style.marginTop = "14px";
    stat.appendChild(el("span", "stat-label", "Next earnings"));
    stat.appendChild(el("span", "stat-value", formatLongDate(data.events.next_earnings_date)));
    analysisPanel.appendChild(stat);
  }
  grid.appendChild(analysisPanel);

  const newsPanel = el("div", "panel");
  newsPanel.style.marginTop = "0";
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
      li.appendChild(el("div", "meta", item.publisher || ""));
      list.appendChild(li);
    });
    newsPanel.appendChild(list);
  } else {
    newsPanel.appendChild(el("p", "empty", "No recent headlines found."));
  }
  grid.appendChild(newsPanel);

  frag.appendChild(grid);
  viewEl.replaceChildren(frag);

  if (history.length >= 2) setupChart(canvas, history);
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
  return "$" + value.toLocaleString(undefined, {
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

  panel.appendChild(el("div", "brief-body", "Reading your watchlist..."));
  return panel;
}

async function loadBrief(panel, force) {
  const body = panel.querySelector(".brief-body");
  body.replaceChildren(el("p", null, force ? "Rewriting..." : "Reading your watchlist..."));

  let data;
  try {
    const res = await fetch("/api/brief" + (force ? "?t=" + Date.now() : ""));
    data = await res.json();
  } catch (err) {
    body.replaceChildren(el("p", null, "Brief unavailable: " + err));
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
    panel.appendChild(el("p", "brief-meta", `Written ${data.generated_at} from the data below. Not financial advice.`));
  }
}

/* ---------------- discover ---------------- */

async function showDiscover() {
  state.view = "discover";
  setActiveNav("discover");
  viewEl.replaceChildren(el("p", "loading-text", "Scanning the market..."));

  let data;
  try {
    const res = await fetch("/api/discover");
    data = await res.json();
  } catch (err) {
    viewEl.replaceChildren(el("p", "empty", "Discover failed: " + err));
    return;
  }

  const frag = document.createDocumentFragment();
  const head = el("div", "view-head");
  head.appendChild(el("h1", null, "Discover"));
  frag.appendChild(head);
  frag.appendChild(
    el("p", "view-sub", "What's moving across the market today that isn't on your list.")
  );

  const scanned = data.scanned || 0;
  frag.appendChild(
    el(
      "p",
      "note",
      data.source === "fallback"
        ? `The market scanner didn't respond, so this is a fixed list of ${scanned} large caps instead of a live market scan. Not a recommendation to buy anything.`
        : `Scanned ${scanned} names across the whole US market (gainers, losers and unusually active, all above $2B and $5 a share). ` +
          `This reports what happened, not what to buy.`
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
          tag.addEventListener("click", () => showDetail(sym));
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

  frag.appendChild(el("p", "section-heading", "Biggest moves you don't own"));
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
  state.view = "search";
  setActiveNav(null);
  viewEl.replaceChildren(el("p", "loading-text", `Searching for ${query}...`));

  let data;
  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    data = await res.json();
  } catch (err) {
    viewEl.replaceChildren(el("p", "empty", "Search failed: " + err));
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

  frag.appendChild(el("p", "view-sub", "Click to open, or add it to your watchlist."));

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

    const add = el("button", "remove", "+");
    add.type = "button";
    add.title = `Add ${result.ticker} to watchlist`;
    add.addEventListener("click", (e) => {
      e.stopPropagation();
      addTicker(result.ticker);
    });
    row.appendChild(add);

    row.addEventListener("click", () => showDetail(result.ticker));
    list.appendChild(row);
  });

  frag.appendChild(list);
  viewEl.replaceChildren(frag);
}

/* ---------------- mutations ---------------- */

async function addTicker(ticker) {
  await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker }),
  });
  showWatchlist(false);
}

async function removeTicker(ticker) {
  await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
  showWatchlist(state.view === "movers");
}

/* ---------------- wiring ---------------- */

document.querySelectorAll(".nav-item[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.dataset.view === "discover") showDiscover();
    else showWatchlist(btn.dataset.view === "movers");
  });
});

document.getElementById("add-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("ticker-input");
  const ticker = input.value.trim().toUpperCase();
  if (!ticker) return;
  input.value = "";
  addTicker(ticker);
});

document.getElementById("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("search-input");
  const query = input.value.trim().toUpperCase();
  if (!query) return;
  showSearch(query);
});

loadOverview();
showWatchlist(false);
