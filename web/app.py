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

from flask import Flask, jsonify, request, send_from_directory
from anthropic import Anthropic

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import MODEL
from tools.market_data import (
    get_stock_price,
    get_recent_news,
    get_upcoming_events,
    get_price_history,
)
from tools.market_scan import get_market_movers, filter_quality, get_market_news
from tools.fundamentals import (
    get_earnings_schedule,
    get_quarterly_results,
    get_key_stats,
    get_earnings_setup,
)

# The conversational agent, reused as-is. The dashboard and the chat panel
# are now two front doors onto one implementation rather than two codebases.
import agent as conversational_agent

app = Flask(__name__, static_folder="static")
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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

Each headline now comes with a short summary of the piece. Use them. The reader's actual \
problem is that there are six items and they don't want to open six tabs, so tell them what \
the coverage collectively says -- and if the pieces disagree, or one is about something \
unrelated to the price move, say that. Two articles under similar headlines often give \
different reasons, and that difference is usually the most useful thing on the page.

Write 3-4 sentences covering: how the move looks in context (including versus the market, \
if that figure is provided), what the coverage says may be driving it, and what is coming \
up that's worth watching.

Some items are videos rather than articles; their summaries are still fine to use, but \
don't describe a video as something the reader can read.

If earnings_setup is present and a report is close, say what the evidence shows about how \
this stock handles earnings -- the typical size of the move, and whether beating estimates \
has actually meant the stock rose. Never say which way it will go this time; that isn't \
knowable and stating it would be invention in a confident voice.

Stick to what you were given. Don't add background about the company from your own memory \
-- not its history, not its usual volatility, not what its products do. Your training data \
is old and the reader can't tell which half of a sentence was looked up and which half you \
recalled.

Rules: no buy/sell/hold recommendations, no price targets, no predictions of direction. \
Don't assert causation -- write "may be related to" rather than "because of". If the data \
is thin or contradictory, say so plainly rather than filling space. No preamble, no \
headings, no bullet points."""


def analyze(ticker: str, data: dict) -> str:
    if not data.get("price") and not data.get("news"):
        return "Not enough data available for this ticker to say anything useful."

    payload = {
        "ticker": ticker,
        "price": data.get("price"),
        "market_comparison": data.get("market"),
        "news": data.get("news"),
        "events": data.get("events"),
        "earnings_setup": data.get("setup"),
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
        # Seven independent network calls. Run sequentially this page took
        # long enough to feel broken; in parallel it's bounded by the
        # slowest one.
        jobs = {
            "price": lambda: get_stock_price(ticker),
            "history": lambda: get_price_history(ticker, period="6mo"),
            "news": lambda: get_recent_news(ticker, limit=6),
            "events": lambda: get_upcoming_events(ticker),
            "earnings": lambda: get_earnings_schedule(ticker),
            "quarters": lambda: get_quarterly_results(ticker),
            "stats": lambda: get_key_stats(ticker),
            "setup": lambda: get_earnings_setup(ticker),
            "spy": spy_change_percent,
        }

        def run(item):
            key, fn = item
            try:
                return key, fn(), None
            except Exception as exc:
                return key, None, str(exc)

        data: dict = {"ticker": ticker}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for key, value, error in pool.map(run, jobs.items()):
                if error:
                    data[f"{key}_error"] = error
                else:
                    data[key] = value

        data.setdefault("history", [])
        data.setdefault("news", [])
        data.setdefault("events", {})
        data.setdefault("quarters", [])
        data.setdefault("stats", {})
        data.setdefault("setup", {})

        market_pct = data.pop("spy", None)
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


# --- discovery --------------------------------------------------------
# Yahoo's screener returns a ranked slice of the WHOLE US market in one
# request, already filtered to real companies (market cap > $2B, price >
# $5, meaningful volume). That's the difference between monitoring a list
# you picked and actually discovering something you didn't know to look
# at.
#
# FALLBACK_UNIVERSE is only used if the screener endpoint fails, so the
# page degrades to something rather than nothing.
FALLBACK_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "AMD", "INTC",
    "CRM", "ORCL", "ADBE", "NFLX", "QCOM", "MU", "PLTR", "UBER", "JPM", "BAC",
    "GS", "V", "MA", "COIN", "JNJ", "UNH", "LLY", "PFE", "MRK", "XOM",
    "CVX", "CAT", "BA", "GE", "WMT", "COST", "HD", "MCD", "NKE", "DIS",
]

THEMES_SYSTEM = """You are given today's biggest market movers and some broad market \
headlines. Find the 2-4 patterns that connect them -- a sector moving together, a policy \
or macro event with several names attached, an earnings cluster.

Return ONLY a JSON array, no prose and no code fences. Each object:
  {"theme": "<6 words max>", "what": "<1-2 sentences on what happened and why these names \
move together>", "tickers": ["<symbols involved>"]}

Only group names that genuinely share a cause. If a big mover is idiosyncratic, don't force \
it into a theme -- a single-name theme is fine when the story really is about one company. \
If nothing connects, return fewer themes rather than inventing links.

No buy/sell advice, no price targets, no predictions."""


def extract_themes(movers: list[dict], news: list[dict]) -> list[dict]:
    """Cluster today's movers into themes. Returns [] on any failure --
    the mover list is still useful without it."""
    if not movers:
        return []

    payload = {
        "movers": [
            {
                "ticker": m["ticker"],
                "name": m.get("name"),
                "change_percent": m.get("change_percent"),
                "in_screens": m.get("screens"),
                "top_headline": m.get("top_headline"),
            }
            for m in movers
        ],
        "market_headlines": [n["title"] for n in news[:12]],
    }

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=THEMES_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception:
        return []

    # Models sometimes wrap JSON in code fences despite instructions, so
    # strip them before parsing rather than trusting the format.
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(parsed, list):
        return []

    themes = []
    for item in parsed[:4]:
        if not isinstance(item, dict) or not item.get("theme"):
            continue
        themes.append(
            {
                "theme": str(item.get("theme"))[:80],
                "what": str(item.get("what", ""))[:400],
                "tickers": [str(t)[:12] for t in (item.get("tickers") or [])][:8],
            }
        )
    return themes


def enrich_mover(mover: dict, market_pct: float) -> dict:
    ticker = mover["ticker"]
    try:
        news = get_recent_news(ticker, limit=4)
    except Exception:
        news = []
    try:
        events = get_upcoming_events(ticker)
    except Exception:
        events = {}
    try:
        history = get_price_history(ticker, period="1mo")
    except Exception:
        history = []

    price = {
        "ticker": ticker,
        "price": mover.get("price"),
        "change_percent": mover.get("change_percent"),
        "currency": "USD",
    }
    return {
        "ticker": ticker,
        "name": mover.get("name"),
        "price": price,
        "history": history,
        "news_count": len(news),
        "top_headline": news[0]["title"] if news else None,
        "events": events,
        "screens": mover.get("screens", []),
        "attention": compute_attention(price, news, events, market_pct),
    }


def discover_payload() -> dict:
    """Two-stage scan.

    Stage 1 is one screener request covering the whole market. Stage 2
    fetches news, earnings and history for only the top eight. Reading
    headlines for every mover would take minutes and the discarded names
    never needed them.
    """
    watching = set(load_watchlist())
    market_pct = spy_change_percent() or 0.0

    movers = get_market_movers()
    source = "screener"

    if not movers:
        # Screener unavailable -- fall back to quoting a fixed list so the
        # page shows something, and say so in the response.
        source = "fallback"
        with ThreadPoolExecutor(max_workers=12) as pool:
            quotes = [q for q in pool.map(safe_price, FALLBACK_UNIVERSE) if q]
        movers = [
            {
                "ticker": q["ticker"],
                "name": q["ticker"],
                "price": q.get("price"),
                "change_percent": q.get("change_percent"),
                "market_cap": MIN_CAP_BYPASS,
                "screens": [],
            }
            for q in quotes
        ]

    scanned = len(movers)
    candidates = filter_quality(movers, exclude=watching)
    candidates.sort(key=lambda m: abs((m.get("change_percent") or 0) - market_pct), reverse=True)
    shortlist = candidates[:8]

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda m: enrich_mover(m, market_pct), shortlist))
    rows.sort(key=lambda r: r["attention"]["score"], reverse=True)

    try:
        headlines = get_market_news()
    except Exception:
        headlines = []

    return {
        "rows": rows,
        "themes": extract_themes(rows, headlines),
        "market_headlines": headlines[:8],
        "scanned": scanned,
        "source": source,
        "market_change_percent": market_pct,
    }


def safe_price(ticker: str):
    try:
        return get_stock_price(ticker)
    except Exception:
        return None


# Fallback rows skip the market-cap gate -- the fixed list is large caps
# by construction, and the screener's own cap data isn't available there.
MIN_CAP_BYPASS = 10_000_000_000


# --- daily brief ------------------------------------------------------
BRIEF_SYSTEM = """You write a short daily brief for someone watching a handful of \
stocks. They can see their ranked watchlist and every number right below what you write, \
so don't recite data back at them -- tell them what it adds up to.

Cover, in this order:
1. The most important thing happening across THEIR watchlist today.
2. Anything connecting several names (a sector moving together, a macro event).
3. What's beyond their list: from the market-wide movers and headlines you're given, \
anything genuinely worth their attention that isn't on their watchlist -- name the tickers. \
Skip this if nothing out there is notable; don't manufacture a reason to mention something.
4. What's coming this week they should prepare for.

The watchlist is a list of names the reader is TRACKING. It is not a portfolio and this app
has no holdings data, so never write "you own", "your holdings" or "your position" -- write
"on your watchlist" or "you're tracking".

If it's a quiet day, say so in a line rather than inflating it -- that's useful too.

Three or four short paragraphs. No headings, no bullet points, no preamble.

HARD RULES

No trading advice: no buy/sell/hold, no price targets, no predictions about which way a \
price will go.

No posture advice. Don't tell the reader how to be positioned, even without naming a \
trade: not "a day for caution", not "this is about preservation, not action", not "steady \
as it goes", not "sit tight", not "if you've been watching from the sidelines". Whether to \
hold, trim, add or do nothing is entirely theirs.

But DO tell them what to pay attention to -- that is the whole job. "NVDA reports \
Wednesday", "the one headline that matters today is X", "worth watching whether the export \
rules get clarified", "that's the next scheduled event on this list" are all correct and \
wanted. The line is ATTENTION versus POSITION: what to look at is yours to say, what to do \
with their money is not.

State calendar facts directly rather than through what the reader might be doing with \
them. "AAPL, MSFT and KO have nothing scheduled this week" -- not "if you're watching for \
catalysts, the calendar isn't offering any just yet", which says the same thing while \
implying they should wait. The direct version is also shorter.

Name companies by ticker symbol -- NVDA, not Nvidia -- since that is how they appear on \
screen beside what you write.

Never assert a cause you were not given. You get headlines and price moves, which show \
things happening together, not one causing the other. Write "fell 8%, which may be \
related to the export rules reported this morning". Never "fell 8% as/after/because the \
export rules widened" -- those state the link as established fact, and you don't know it.

Stick to the data you were handed. Don't add specifics about the event from your own \
memory: your training data is old, and an invented detail is worse than a missing one."""


def build_brief(rows: list[dict], market_pct, indices: list[dict],
                movers: list[dict], headlines: list[dict]) -> str:
    """One Claude call covering the watchlist AND the wider market.

    The payload is deliberately compacted -- sending full news bodies for
    every name would be slow and expensive without making the brief better.
    """
    if not rows:
        return "Your watchlist is empty, so there's nothing to brief on yet."

    payload = {
        "market": {
            "spy_change_percent": market_pct,
            "indices": [
                {"label": i.get("label"), "change_percent": i.get("change_percent")}
                for i in indices if not i.get("error")
            ],
            "session": market_status(),
        },
        "watchlist": [
            {
                "ticker": r["ticker"],
                "change_percent": (r.get("price") or {}).get("change_percent"),
                "attention": (r.get("attention") or {}).get("level"),
                "reasons": [f["label"] for f in (r.get("attention") or {}).get("factors", [])],
                "top_headline": r.get("top_headline"),
            }
            for r in rows
        ],
        "market_wide_movers_not_on_watchlist": [
            {
                "ticker": m["ticker"],
                "name": m.get("name"),
                "change_percent": m.get("change_percent"),
                "in_screens": m.get("screens"),
            }
            for m in movers[:15]
        ],
        "market_headlines": [h["title"] for h in headlines[:10]],
    }

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=BRIEF_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return f"(Brief unavailable: {exc})"


# --- earnings calendar ------------------------------------------------
# The one genuinely forward-looking thing in the app. Everything else
# reports what already happened; this is what lets you prepare.
# --- chat -------------------------------------------------------------
MAX_HISTORY_TURNS = 12
MAX_MESSAGE_CHARS = 2000


def clean_history(raw) -> list[dict]:
    """Trust nothing from the client.

    Only text turns are replayed -- prior tool_use blocks are dropped
    rather than reconstructed. The model loses the raw tool output from
    earlier turns but keeps what it concluded from it, which is enough for
    follow-up questions and avoids replaying a growing pile of JSON on
    every message.
    """
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})
    # A conversation must start with a user turn and alternate sanely.
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


@app.route("/api/chat", methods=["POST"])
def chat_route():
    body = request.get_json(force=True, silent=True) or {}
    question = (body.get("message") or "").strip()[:MAX_MESSAGE_CHARS]
    if not question:
        return jsonify({"error": "message is required"}), 400

    trace: list[dict] = []
    try:
        answer = conversational_agent.ask_agent(
            client,
            question,
            verbose=False,
            history=clean_history(body.get("history")),
            trace=trace,
        )
    except Exception as exc:
        return jsonify({"error": f"{type(exc).__name__}: {exc}", "trace": trace}), 500

    return jsonify({"answer": answer, "trace": trace})


@app.route("/api/earnings")
def earnings_route():
    tickers = load_watchlist()

    def produce():
        with ThreadPoolExecutor(max_workers=6) as pool:
            items = list(pool.map(get_earnings_schedule, tickers))

        scheduled = [i for i in items if i.get("next_date")]
        scheduled.sort(key=lambda i: i["next_date"])
        unscheduled = [i["ticker"] for i in items if not i.get("next_date")]

        # Surface which source answered, so an empty calendar can be
        # diagnosed from the page instead of guessed at.
        sources = sorted({i.get("source") for i in scheduled if i.get("source")})

        return {
            "items": scheduled,
            "unscheduled": unscheduled,
            "count": len(items),
            "sources": sources,
            "today": datetime.now(ZoneInfo("America/New_York")).date().isoformat(),
        }

    return jsonify(cached("earnings:" + ",".join(tickers), 1800, produce))


@app.route("/api/brief")
def brief_route():
    tickers = load_watchlist()

    def produce():
        market_pct = spy_change_percent()

        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(lambda t: fetch_row(t, market_pct), tickers))
        rows.sort(key=lambda r: r["attention"]["score"], reverse=True)

        with ThreadPoolExecutor(max_workers=4) as pool:
            indices = list(pool.map(lambda pair: index_quote(*pair), INDICES))

        # Market-wide context so the brief can look beyond the watchlist.
        try:
            movers = filter_quality(get_market_movers(), exclude=set(tickers))
            movers.sort(key=lambda m: abs((m.get("change_percent") or 0) - (market_pct or 0)),
                        reverse=True)
        except Exception:
            movers = []
        try:
            headlines = get_market_news()
        except Exception:
            headlines = []

        return {
            "brief": build_brief(rows, market_pct, indices, movers, headlines),
            "generated_at": datetime.now(ZoneInfo("America/New_York")).strftime("%I:%M %p ET").lstrip("0"),
            "scanned_market": len(movers),
        }

    # 15 minutes: regenerating on every refresh burns tokens to say the
    # same thing.
    return jsonify(cached("brief:" + ",".join(tickers), 900, produce))


@app.route("/api/discover")
def discover_route():
    watching = load_watchlist()

    def produce():
        return discover_payload()

    return jsonify(cached("discover:" + ",".join(watching), 600, produce))


if __name__ == "__main__":
    print("\nMarket Agent -- open http://127.0.0.1:5050 in your browser\n")
    app.run(debug=True, port=5050)
