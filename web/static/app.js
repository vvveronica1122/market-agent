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

const state = { view: "watchlist", rows: [], chart: null, chat: [], chatBusy: false };

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

  // Fundamentals: the numbers behind the price.
  const quarters = data.quarters || [];
  const stats = data.stats || {};
  const earnings = data.earnings || {};

  if (quarters.length || Object.keys(stats).length || earnings.next_date) {
    const fPanel = el("div", "panel");
    fPanel.appendChild(el("h2", null, "Fundamentals"));

    // Every figure says what it means. A number a reader can't interpret
    // isn't information, it's decoration.
    const metrics = el("div", "metrics");
    const defs = [];

    if (stats.market_cap) {
      defs.push(["$" + bigMoney(stats.market_cap), "Company value",
                 "What the whole company is worth at today's share price.", ""]);
    }
    if (stats.trailing_pe) {
      defs.push([num(stats.trailing_pe, 1), "Price to earnings",
                 `You pay $${num(stats.trailing_pe, 2)} for every $1 the company earned over the past year. ` +
                 `Higher means the market expects more growth — or that it's expensive.`, ""]);
    }
    if (stats.profit_margin_percent !== null && stats.profit_margin_percent !== undefined) {
      defs.push([num(stats.profit_margin_percent, 1) + "%", "Profit margin",
                 `Keeps ${num(stats.profit_margin_percent, 1)} cents of every dollar of sales as profit, after all costs.`,
                 toneClass(stats.profit_margin_percent)]);
    }
    if (stats.revenue_growth_percent !== null && stats.revenue_growth_percent !== undefined) {
      const g = stats.revenue_growth_percent;
      defs.push([num(g, 1) + "%", "Revenue growth",
                 `Sales are ${g >= 0 ? "higher" : "lower"} than the same period a year ago.`,
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
    if (defs.length) fPanel.appendChild(metrics);

    if (quarters.length) {
      const label = el("p", "section-heading", "Quarterly revenue — oldest to newest");
      label.style.margin = "22px 0 4px";
      fPanel.appendChild(label);
      const explain = el("p", "metric-note",
        "Each bar is one three-month reporting period, in date order. Quarterly rather than " +
        "yearly because most businesses are seasonal — a December quarter often looks nothing " +
        "like a March one.");
      explain.style.margin = "0 0 10px";
      fPanel.appendChild(explain);
      const barWrap = el("div", "chart-wrap");
      const barCanvas = el("canvas", "bar-chart");
      barCanvas.setAttribute("role", "img");
      barCanvas.setAttribute("aria-label",
        `Quarterly revenue for ${data.ticker}: ` +
        quarters.map((q) => `${periodLabel(q.period)} $${bigMoney(q.revenue)}`).join(", "));
      barWrap.appendChild(barCanvas);
      fPanel.appendChild(barWrap);

      const latest = quarters[quarters.length - 1];
      const yearAgo = quarters.length >= 5 ? quarters[quarters.length - 5] : null;
      if (yearAgo && yearAgo.revenue) {
        const yoy = ((latest.revenue - yearAgo.revenue) / yearAgo.revenue) * 100;
        const note = el("p", "view-sub",
          `Most recent quarter $${bigMoney(latest.revenue)}, ` +
          `${yoy >= 0 ? "up" : "down"} ${Math.abs(yoy).toFixed(1)}% from the same quarter a year earlier. ` +
          `Year-over-year rather than quarter-to-quarter, since many businesses are seasonal.`);
        note.style.margin = "12px 0 0";
        fPanel.appendChild(note);
      }
    }

    if (earnings.next_date) {
      const eRow = el("div", "stat-line");
      eRow.style.marginTop = "16px";
      const stat = el("div", "stat");
      stat.appendChild(el("span", "stat-label", "Next earnings"));
      stat.appendChild(el("span", "stat-value",
        formatLongDate(earnings.next_date) +
        (earnings.days_away !== null && earnings.days_away !== undefined ? `  ·  in ${earnings.days_away}d` : "")));
      eRow.appendChild(stat);

      if (earnings.eps_estimate !== null && earnings.eps_estimate !== undefined) {
        const est = el("div", "stat");
        est.appendChild(el("span", "stat-label", "EPS estimate"));
        est.appendChild(el("span", "stat-value", num(earnings.eps_estimate)));
        eRow.appendChild(est);
      }

      const last = earnings.last_report;
      if (last && last.surprise_percent !== null && last.surprise_percent !== undefined) {
        const surprise = el("div", "stat");
        surprise.appendChild(el("span", "stat-label", "Last quarter"));
        surprise.appendChild(el("span", "stat-value " + toneClass(last.surprise_percent),
          (last.surprise_percent >= 0 ? "Beat by " : "Missed by ") + Math.abs(last.surprise_percent).toFixed(1) + "%"));
        eRow.appendChild(surprise);
      }
      fPanel.appendChild(eRow);
    }

    frag.appendChild(fPanel);
  }

  const setupBuilt = buildSetupPanel(data.setup, data.ticker,
                                     (data.earnings || {}).days_away);
  if (setupBuilt) frag.appendChild(setupBuilt.panel);

  // Analysis + news side by side
  const grid = el("div", "grid-2");

  const analysisPanel = el("div", "panel");
  analysisPanel.style.marginTop = "0";
  analysisPanel.appendChild(el("h2", null, "What's going on"));
  analysisPanel.appendChild(el("p", "analysis", data.analysis || "No analysis available."));
  // The earnings date lives in the Fundamentals panel above, with the
  // estimate and last quarter's surprise next to it -- repeating it here
  // would be the same fact twice with less context.
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
    newsPanel.appendChild(el("p", "empty", "No recent headlines found."));
  }
  grid.appendChild(newsPanel);

  frag.appendChild(grid);
  viewEl.replaceChildren(frag);

  if (history.length >= 2) setupChart(canvas, history);

  const barCanvas = viewEl.querySelector("canvas.bar-chart");
  if (barCanvas && quarters.length) setupBarChart(barCanvas, quarters);

  if (setupBuilt) {
    drawReactionChart(setupBuilt.canvas, setupBuilt.reactions);
    if (window.ResizeObserver) {
      new ResizeObserver(() => drawReactionChart(setupBuilt.canvas, setupBuilt.reactions))
        .observe(setupBuilt.canvas);
    }
  }
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
  return d.toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function num(value, digits) {
  if (value === null || value === undefined) return "--";
  return Number(value).toFixed(digits === undefined ? 2 : digits);
}

/* ---------------- earnings calendar ---------------- */

async function showEarnings() {
  state.view = "earnings";
  setActiveNav("earnings");
  viewEl.replaceChildren(el("p", "loading-text", "Loading earnings dates..."));

  let data;
  try {
    const res = await fetch("/api/earnings");
    data = await res.json();
  } catch (err) {
    viewEl.replaceChildren(el("p", "empty", "Could not load earnings: " + err));
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
      el("p", "view-sub", "No earnings dates came back for your watchlist.")
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
      btn.addEventListener("click", () => showDetail(item.ticker));
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
    tag.addEventListener("click", () => showDetail(t));
    wrap.appendChild(tag);
  });
  return wrap;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function buildMonth(year, monthIndex, byDate, todayIso) {
  const first = new Date(year, monthIndex, 1);
  const monthName = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });

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
        tag.addEventListener("click", () => showDetail(item.ticker));
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

  const lead = el("p", "setup-lead");
  lead.appendChild(el("span", "setup-figure", "\u00b1" + num(setup.median_abs_move, 1) + "%"));
  lead.appendChild(el("span", null,
    ` typical move the session after ${ticker} reports, across its last ` +
    `${setup.reactions.length} reports.`));
  panel.appendChild(lead);

  // The finding worth leading with, when it applies: beating estimates
  // has not meant the stock rose. Markets price the expectation, not the
  // analyst number.
  if (setup.beat_count >= 3 && setup.beat_but_fell > 0) {
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
    "Price move the session after each past earnings report: " +
    setup.reactions.map((r) => `${r.date} ${r.next_session_move > 0 ? "up" : "down"} ` +
      `${Math.abs(r.next_session_move)} percent`).join(", "));
  wrap.appendChild(canvas);
  panel.appendChild(wrap);

  const legend = el("p", "metric-note");
  legend.textContent =
    "Each bar is one past report: how the price moved the following session. " +
    "Green above the line, red below. This is what happened, not what will.";
  legend.style.margin = "10px 0 0";
  panel.appendChild(legend);

  const trend = setup.estimate_trend;
  if (trend && (trend.current || trend.days_90)) {
    const stats = el("div", "stat-line");
    stats.style.marginTop = "16px";
    if (trend.current && trend.days_90) {
      const shift = ((trend.current - trend.days_90) / Math.abs(trend.days_90)) * 100;
      const stat = el("div", "stat");
      stat.appendChild(el("span", "stat-label", "Estimate vs 90 days ago"));
      stat.appendChild(el("span", "stat-value " + toneClass(shift),
        (shift >= 0 ? "+" : "") + num(shift, 0) + "%"));
      stats.appendChild(stat);
    }
    if (trend.up_last_30_days !== null && trend.up_last_30_days !== undefined) {
      const stat = el("div", "stat");
      stat.appendChild(el("span", "stat-label", "Revisions last 30 days"));
      stat.appendChild(el("span", "stat-value",
        `${num(trend.up_last_30_days, 0)} up / ${num(trend.down_last_30_days, 0)} down`));
      stats.appendChild(stat);
    }
    panel.appendChild(stats);
  }

  return { panel, canvas, reactions: setup.reactions };
}

const REACT_PAD = { left: 8, right: 8, top: 22, bottom: 30 };

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
  const values = points.map((r) => r.next_session_move);
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
    const value = r.next_session_move;
    const x = REACT_PAD.left + slot * i + (slot - barW) / 2;
    const h = Math.max(2, (Math.abs(value) / extent) * (plotH / 2 - 4));
    const up = value >= 0;
    const y = up ? zeroY - h : zeroY;

    ctx.fillStyle = up ? COLORS.up : COLORS.down;
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

    ctx.fillStyle = up ? COLORS.up : COLORS.down;
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

const STARTERS = [
  "Which of my stocks reports soonest, and how did they do last quarter?",
  "What moved most in the market today that isn't on my watchlist?",
  "Compare the profit margins of the companies on my watchlist.",
];

async function showChat() {
  state.view = "chat";
  setActiveNav("chat");

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
  input.placeholder = "Ask about your watchlist or the market";
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
    empty.appendChild(el("p", "chat-empty-title", "Try one of these"));
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

  frag.appendChild(el("p", "section-heading", "Biggest moves outside your watchlist"));
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
    if (btn.dataset.view === "chat") showChat();
    else if (btn.dataset.view === "discover") showDiscover();
    else if (btn.dataset.view === "earnings") showEarnings();
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
