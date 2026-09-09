const cardsEl = document.getElementById("cards");
const emptyStateEl = document.getElementById("empty-state");
const addForm = document.getElementById("add-form");
const tickerInput = document.getElementById("ticker-input");

async function loadWatchlist() {
  const res = await fetch("/api/watchlist");
  const tickers = await res.json();
  renderWatchlist(tickers);
}

function renderWatchlist(tickers) {
  cardsEl.innerHTML = "";
  emptyStateEl.hidden = tickers.length > 0;
  tickers.forEach((ticker) => {
    const card = createLoadingCard(ticker);
    cardsEl.appendChild(card);
    loadAnalysis(ticker, card);
  });
}

function createLoadingCard(ticker) {
  const card = document.createElement("section");
  card.className = "card loading";
  card.dataset.ticker = ticker;
  card.innerHTML = `
    <div class="card-header">
      <h2>${escapeHtml(ticker)}</h2>
      <button class="remove-btn" title="Remove">Remove</button>
    </div>
    <div class="price-row"><span class="price">Loading...</span></div>
  `;
  card.querySelector(".remove-btn").addEventListener("click", () => removeTicker(ticker));
  return card;
}

async function loadAnalysis(ticker, card) {
  try {
    const res = await fetch(`/api/analysis/${encodeURIComponent(ticker)}`);
    const data = await res.json();
    renderCard(card, data);
  } catch (err) {
    card.classList.remove("loading");
    card.querySelector(".price-row").innerHTML = `<span class="error-text">Failed to load: ${escapeHtml(String(err))}</span>`;
  }
}

function renderCard(card, data) {
  card.classList.remove("loading");

  const priceBlock = data.price
    ? `
      <div class="price-row">
        <span class="price">$${data.price.price.toFixed(2)}</span>
        ${
          data.price.change !== null && data.price.change !== undefined
            ? `<span class="change ${data.price.change >= 0 ? "up" : "down"}">
                 ${data.price.change >= 0 ? "+" : ""}${data.price.change.toFixed(2)}
                 (${data.price.change_percent >= 0 ? "+" : ""}${data.price.change_percent.toFixed(2)}%)
               </span>`
            : ""
        }
      </div>
    `
    : `<div class="price-row"><span class="error-text">${escapeHtml(data.price_error || "Price unavailable")}</span></div>`;

  const sparklineBlock = `<canvas class="sparkline" width="280" height="48"></canvas>`;

  const summaryBlock = data.summary
    ? `<div><p class="section-label">Summary</p><p class="summary">${escapeHtml(data.summary)}</p></div>`
    : "";

  const newsBlock = data.news && data.news.length
    ? `
      <div>
        <p class="section-label">Recent News</p>
        <ul class="news-list">
          ${data.news
            .slice(0, 3)
            .map(
              (item) => `
                <li>
                  <a href="${escapeHtml(item.link || "#")}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
                  <div class="publisher">${escapeHtml(item.publisher || "")}</div>
                </li>
              `
            )
            .join("")}
        </ul>
      </div>
    `
    : "";

  const eventsBlock = data.events && data.events.next_earnings_date
    ? `<div class="events-row"><span class="label">Next earnings:</span> ${escapeHtml(data.events.next_earnings_date)}</div>`
    : "";

  card.innerHTML = `
    <div class="card-header">
      <h2>${escapeHtml(data.ticker)}</h2>
      <button class="remove-btn" title="Remove">Remove</button>
    </div>
    ${priceBlock}
    ${sparklineBlock}
    ${summaryBlock}
    ${newsBlock}
    ${eventsBlock}
  `;
  card.querySelector(".remove-btn").addEventListener("click", () => removeTicker(data.ticker));

  const canvas = card.querySelector(".sparkline");
  if (canvas && data.history) {
    drawSparkline(canvas, data.history);
  }
}

function drawSparkline(canvas, points) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!points || points.length < 2) return;

  const closes = points.map((p) => p.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const stepX = w / (closes.length - 1);
  const up = closes[closes.length - 1] >= closes[0];

  ctx.strokeStyle = up ? "#3ecf8e" : "#f26d6d";
  ctx.lineWidth = 2;
  ctx.beginPath();
  closes.forEach((c, i) => {
    const x = i * stepX;
    const y = h - ((c - min) / range) * (h - 6) - 3;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function addTicker(ticker) {
  await fetch("/api/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker }),
  });
  await loadWatchlist();
}

async function removeTicker(ticker) {
  await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
  await loadWatchlist();
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

addForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const ticker = tickerInput.value.trim().toUpperCase();
  if (!ticker) return;
  tickerInput.value = "";
  addTicker(ticker);
});

loadWatchlist();
