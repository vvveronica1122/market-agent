"""
Market Agent -- web dashboard backend.

Design note, since this project exists to learn from:

`agent.py` uses the full agentic loop -- Claude decides which tools to call.
This server deliberately does the opposite for the list view. It already
knows every row needs price + history + news + events, so it calls those
tools directly (in parallel) and computes an "attention score" in plain
Python. No LLM is involved in ranking.

Claude is used for exactly one job here: writing the analysis on a single
stock's detail page, where language actually adds something the numbers
don't. That split -- deterministic rules for ranking, an LLM for
interpretation -- is usually the right one. LLMs make poor sorting
functions (slow, costly, inconsistent between runs) and good explainers.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.market_data import (
    get_stock_price,
    get_recent_news,
    get_upcoming_events,
    get_price_history,
)

load_dotenv(PROJECT_ROOT / ".env")

app = Flask(__name__, static_folder="static")
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

MODEL = "claude-sonnet-4-5"
WATCHLIST_FILE = Path(__file__).resolve().parent / "watchlist.json"
DEFAULT_WATCHLIST = ["AAPL", "TSLA", "MSFT", "NVDA"]
INDICES = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq 100"),
    ("DIA", "Dow"),
    ("IWM", "Russell 2000"),
]

# --- a tiny TTL cache -------------------------------------------------
# yfinance is slow (several HTTP calls per ticker) and prices don't change
# meaningfully between two page loads a few seconds apart. Without this,
# every refresh refetches everything and the page feels broken.
_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl_seconds: float, producer):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl_seconds:
        return hit[1]
    value = producer()
    _cache[key] = (now, value)
    return value


# --- watchlist storage ------------------------------------------------
def load_watchlist() -> list[str]:
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return list(DEFAULT_WATCHLIST)


def save_watchlist(tickers: list[str]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(tickers, indent=2))


# --- market state -----------------------------------------------------
def market_status() -> dict:
    """Rough US market session state.

    Note: this does NOT account for market holidays -- on Thanksgiving it
    will happily say "open". Good enough for a dashboard label; if you
    wanted this to be correct you'd need a holiday calendar.
    """
    now = datetime.now(ZoneInfo("America/New_York"))
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)

    if now.weekday() >= 5:
        state = "closed"
    elif now < open_t:
        state = "pre-market"
    elif now > close_t:
        state = "after-hours"
    else:
        state = "open"
    return {"state": state, "time": now.strftime("%I:%M %p ET").lstrip("0")}


# --- attention scoring ------------------------------------------------
# This is the heart of the dashboard. Instead of showing the watchlist
# alphabetically (which makes the reader do the work of finding what
# matters), each name is scored on how much it deserves attention today
# and the list is sorted by that score.
def days_until_earnings(events: dict | None) -> int | None:
    raw = (events or {}).get("next_earnings_date")
    if not raw:
        return None
    text = str(raw)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            when = datetime.strptime(text, fmt).date()
            return (when - datetime.now().date()).days
        except ValueError:
            continue
    return None


def compute_attention(price, news, events, market_pct) -> dict:
    score = 0.0
    factors: list[dict] = []

    pct = (price or {}).get("change_percent")
    if pct is not None:
        score += min(abs(pct) * 8, 45)
        if abs(pct) >= 2:
            factors.append({"label": f"{pct:+.1f}% today", "tone": "up" if pct > 0 else "down"})

        # A move only means something relative to the market. -3% on a day
        # the whole market is down 3% is not news; -3% on a flat day is.
        if market_pct is not None:
            relative = pct - market_pct
            if abs(relative) >= 1.5:
                score += 12
                factors.append(
                    {
                        "label": f"{relative:+.1f}pt vs market",
                        "tone": "up" if relative > 0 else "down",
                    }
                )

    days = days_until_earnings(events)
    if days is not None and 0 <= days <= 14:
        score += 25 if days <= 7 else 12
        label = "earnings today" if days == 0 else f"earnings in {days}d"
        factors.append({"label": label, "tone": "neutral"})

    count = len(news or [])
    if count:
        score += min(count * 3, 12)
        if count >= 3:
            factors.append({"label": f"{count} headlines", "tone": "neutral"})

    level = "high" if score >= 45 else "medium" if score >= 20 else "quiet"
    return {"score": round(score, 1), "level": level, "factors": factors}


# --- data assembly ----------------------------------------------------
def fetch_row(ticker: str, market_pct) -> dict:
    """Everything one watchlist row needs. Failures degrade, never raise."""
    row: dict = {"ticker": ticker}
    try:
        row["price"] = get_stock_price(ticker)
    except Exception as exc:
        row["error"] = str(exc)
    try:
        row["history"] = get_price_history(ticker, period="1mo")
    except Exception:
        row["history"] = []
    try:
        news = get_recent_news(ticker, limit=5)
    except Exception:
        news = []
    try:
        events = get_upcoming_events(ticker)
    except Exception:
        events = {}

    row["news_count"] = len(news)
    row["top_headline"] = news[0]["title"] if news else None
    row["events"] = events
    row["attention"] = compute_attention(row.get("price"), news, events, market_pct)
    return row


def spy_change_percent():
    try:
        return get_stock_price("SPY").get("change_percent")
    except Exception:
        return None


ANALYSIS_SYSTEM = """You are a market research assistant writing a short briefing on one \
stock, for a reader who can already see the price, chart, headlines and earnings date on \
screen next to what you write.

Write 3-4 sentences covering: how the move looks in context (including versus the market, \
if that figure is provided), what the news suggests may be driving it, and what is coming \
up that's worth watching.

Rules: no buy/sell/hold recommendations, no price targets, no predictions of direction. \
Don't assert causation from correlation -- write "may be related to" rather than "because \
of". If the data is thin or contradictory, say so plainly rather than filling space. No \
preamble, no headings, no bullet points."""


def analyze(ticker: str, data: dict) -> str:
    if not data.get("price") and not data.get("news"):
        return "Not enough data available for this ticker to say anything useful."

    payload = {
        "ticker": ticker,
        "price": data.get("price"),
        "market_comparison": data.get("market"),
        "news": data.get("news"),
        "events": data.get("events"),
    }
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=350,
            system=ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return f"(Analysis unavailable: {exc})"


# --- routes -----------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/overview")
def overview():
    def produce():
        with ThreadPoolExecutor(max_workers=4) as pool:
            quotes = list(pool.map(lambda pair: index_quote(*pair), INDICES))
        return {"indices": quotes, "market": market_status()}

    return jsonify(cached("overview", 60, produce))


def index_quote(ticker: str, label: str) -> dict:
    try:
        price = get_stock_price(ticker)
        return {
            "ticker": ticker,
            "label": label,
            "price": price.get("price"),
            "change_percent": price.get("change_percent"),
        }
    except Exception as exc:
        return {"ticker": ticker, "label": label, "error": str(exc)}


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist_route():
    return jsonify(load_watchlist())


@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    body = request.get_json(force=True, silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400

    watchlist = load_watchlist()
    if ticker not in watchlist:
        watchlist.append(ticker)
        save_watchlist(watchlist)
    return jsonify(watchlist)


@app.route("/api/watchlist/<ticker>", methods=["DELETE"])
def remove_from_watchlist(ticker: str):
    ticker = ticker.strip().upper()
    save_watchlist([t for t in load_watchlist() if t != ticker])
    return jsonify(load_watchlist())


@app.route("/api/watchlist/data")
def watchlist_data():
    tickers = load_watchlist()
    if not tickers:
        return jsonify({"rows": [], "market_change_percent": None})

    def produce():
        market_pct = spy_change_percent()
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(lambda t: fetch_row(t, market_pct), tickers))
        rows.sort(key=lambda r: r["attention"]["score"], reverse=True)
        return {"rows": rows, "market_change_percent": market_pct}

    return jsonify(cached("watchlist:" + ",".join(tickers), 60, produce))


@app.route("/api/stock/<ticker>")
def stock_detail(ticker: str):
    ticker = ticker.strip().upper()

    def produce():
        data: dict = {"ticker": ticker}
        try:
            data["price"] = get_stock_price(ticker)
        except Exception as exc:
            data["price_error"] = str(exc)
        try:
            data["history"] = get_price_history(ticker, period="6mo")
        except Exception as exc:
            data["history"] = []
            data["history_error"] = str(exc)
        try:
            data["news"] = get_recent_news(ticker, limit=6)
        except Exception as exc:
            data["news"] = []
            data["news_error"] = str(exc)
        try:
            data["events"] = get_upcoming_events(ticker)
        except Exception:
            data["events"] = {}

        market_pct = spy_change_percent()
        data["market"] = {"ticker": "SPY", "change_percent": market_pct} if market_pct is not None else None
        data["attention"] = compute_attention(
            data.get("price"), data.get("news"), data.get("events"), market_pct
        )
        data["analysis"] = analyze(ticker, data)
        return data

    return jsonify(cached(f"stock:{ticker}", 120, produce))


@app.route("/api/search")
def search():
    query = (request.args.get("q") or "").strip().upper()
    if not query:
        return jsonify({"results": []})

    # yfinance has no stable free symbol-search endpoint across versions,
    # so we treat the query as a ticker and see whether it resolves.
    try:
        price = get_stock_price(query)
        return jsonify(
            {
                "results": [
                    {
                        "ticker": query,
                        "price": price.get("price"),
                        "change_percent": price.get("change_percent"),
                    }
                ]
            }
        )
    except Exception:
        return jsonify(
            {
                "results": [],
                "message": f"No data found for '{query}'. Try an exact ticker symbol, e.g. NVDA.",
            }
        )


if __name__ == "__main__":
    print("\nMarket Agent -- open http://127.0.0.1:5050 in your browser\n")
    app.run(debug=True, port=5050)
