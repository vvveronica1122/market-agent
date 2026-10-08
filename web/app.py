"""
Market Agent -- web dashboard backend.

Design note, since this project exists to learn from:

`agent.py` uses the full agentic loop -- Claude decides which tools to call.
This server deliberately does the opposite for the list view. It already
knows every row needs price + history + news + events, so it calls those
tools directly (in parallel) and computes an "attention score" in plain
Python. No LLM is involved in ranking.

Claude is used only where language actually adds something the numbers
don't: the daily brief, the analysis on a single stock's detail page, and
grouping Discover's movers into themes. None of it touches the ranking.
That split -- deterministic rules for ranking, an LLM for
interpretation -- is usually the right one. LLMs make poor sorting
functions (slow, costly, inconsistent between runs) and good explainers.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
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
from guards import find_multiple, sentence_around
import themes as theme_store
from themes import ThemeError
from tools.relative import relative_rows, theme_summary
from tools import performance
from tools.market_data import (
    get_stock_price,
    get_recent_news,
    get_upcoming_events,
    get_price_history,
)
from tools.market_scan import get_market_movers, filter_quality, get_market_news
from tools.fundamentals import (
    figure_caveats,
    get_earnings_schedule,
    get_quarterly_results,
    get_key_stats,
    get_earnings_setup,
    get_estimate_revisions,
)

import pandas as pd

# The conversational agent, reused as-is. The dashboard and the chat panel
# are now two front doors onto one implementation rather than two codebases.
import agent as conversational_agent

app = Flask(__name__, static_folder="static")
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

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


# Per-ticker pieces, each cached on its own clock. A price is stale within a
# minute, an earnings date within hours. With four themes and ~20 names,
# refetching everything on every page would mean ~80 Yahoo calls a load --
# and the home page, a theme page and the brief all want the same pieces.
TTL = {"price": 60, "history": 900, "news": 600, "events": 6 * 3600}


def price_of(ticker: str) -> dict:
    return cached(f"price:{ticker}", TTL["price"], lambda: get_stock_price(ticker))


def history_of(ticker: str, period: str = "1mo") -> list:
    return cached(f"history:{ticker}:{period}", TTL["history"],
                  lambda: get_price_history(ticker, period=period))


def news_of(ticker: str, limit: int = 5) -> list:
    return cached(f"news:{ticker}:{limit}", TTL["news"], lambda: get_recent_news(ticker, limit=limit))


def events_of(ticker: str) -> dict:
    return cached(f"events:{ticker}", TTL["events"], lambda: get_upcoming_events(ticker))


def safe(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception:
        return default


# Slower-moving data: earnings history and fundamentals change when a
# company reports, not between page loads.
SLOW_TTL = 6 * 3600


def closes_of(ticker: str, period: str = "2y") -> pd.Series:
    points = history_of(ticker, period)
    return pd.Series([p["close"] for p in points],
                     index=pd.to_datetime([p["date"] for p in points]), dtype=float)


def setup_of(ticker: str) -> dict:
    """The earnings setup with market-model figures. SPY's history is
    passed in from the cache so a theme's companies share one download."""
    def produce():
        market = pd.DataFrame({"Close": closes_of("SPY")})
        return get_earnings_setup(ticker, market_history=market)
    return cached(f"setup:{ticker}", SLOW_TTL, produce)


def stats_of(ticker: str) -> dict:
    return cached(f"stats:{ticker}", SLOW_TTL, lambda: get_key_stats(ticker))


def revisions_of(ticker: str) -> dict:
    return cached(f"revisions:{ticker}", SLOW_TTL, lambda: get_estimate_revisions(ticker))


# --- themes -----------------------------------------------------------
# The watchlist is a set of themes (see themes.py). These wrappers are what
# the routes call, so tests can swap the storage out in one place.
_themes_lock = threading.Lock()


def load_themes() -> dict:
    return theme_store.load()


def save_themes(state: dict) -> None:
    theme_store.save(state)


def load_watchlist() -> list[str]:
    """Every tracked ticker, across all themes."""
    return theme_store.all_tickers(load_themes())


def themes_key(state: dict) -> str:
    """Fingerprint of the theme setup, for cache keys: edit a theme and
    every cached page built from the old setup simply stops matching."""
    return hashlib.sha1(json.dumps(state, sort_keys=True).encode()).hexdigest()[:12]


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


def compute_attention(price, news, events, market_pct, peer_pct=None) -> dict:
    factors: list[dict] = []
    # Each part kept separately, so the page can show how a company got its
    # rank instead of asking the reader to trust a number.
    parts = {"move": 0.0, "relative": 0.0, "earnings": 0.0, "news": 0.0}

    pct = (price or {}).get("change_percent")
    if pct is not None:
        parts["move"] = min(abs(pct) * 8, 45)
        if abs(pct) >= 2:
            # "move", not "today": outside market hours this is the last
            # session's move, and the page says which session that was.
            factors.append({"label": f"{pct:+.1f}% move", "tone": "up" if pct > 0 else "down"})

        # A move only means something relative to what it should be measured
        # against. Inside a theme that's the company's peers: -6% when its
        # peers are -6% is the theme's story, told once on the theme card;
        # -6% when they're flat is this company's. With no peer group to
        # hand, fall back to the market: -3% on a day SPY is -3% isn't news.
        reference, label = (peer_pct, "vs peers") if peer_pct is not None else (market_pct, "vs market")
        if reference is not None:
            relative = pct - reference
            if abs(relative) >= 1.5:
                parts["relative"] = 12
                factors.append(
                    {
                        "label": f"{relative:+.1f}pt {label}",
                        "tone": "up" if relative > 0 else "down",
                    }
                )

    days = days_until_earnings(events)
    if days is not None and 0 <= days <= 14:
        parts["earnings"] = 25 if days <= 7 else 12
        label = "earnings today" if days == 0 else f"earnings in {days}d"
        factors.append({"label": label, "tone": "neutral"})

    count = len(news or [])
    if count:
        parts["news"] = min(count * 3, 12)
        if count >= 3:
            factors.append({"label": f"{count} headlines", "tone": "neutral"})

    score = sum(parts.values())
    level = "high" if score >= 45 else "medium" if score >= 20 else "quiet"
    return {"score": round(score, 1), "level": level, "factors": factors,
            "parts": {k: round(v, 1) for k, v in parts.items()},
            "reference": "peers" if peer_pct is not None else "market"}


# --- data assembly ----------------------------------------------------
def fetch_row(ticker: str, market_pct, peer_pct=None) -> dict:
    """Everything one watchlist row needs. Failures degrade, never raise."""
    row: dict = {"ticker": ticker}
    try:
        row["price"] = price_of(ticker)
    except Exception as exc:
        row["error"] = str(exc)
    row["history"] = safe(history_of, ticker, default=[])
    news = safe(news_of, ticker, default=[])
    events = safe(events_of, ticker, default={})

    row["news_count"] = len(news)
    row["top_headline"] = news[0]["title"] if news else None
    row["events"] = events
    row["attention"] = compute_attention(row.get("price"), news, events, market_pct, peer_pct)
    return row


def spy_change_percent():
    return (safe(price_of, "SPY") or {}).get("change_percent")


def rounded(value, digits=2):
    return None if value is None else round(value, digits)


def theme_block(theme: dict, rows_by_ticker: dict, quotes: dict, market_pct) -> dict:
    """One theme as the pages show it: its benchmark, how it did as a whole,
    and each company measured against the benchmark and against its peers."""
    bench = quotes.get(theme["benchmark"]) or {}
    bench_pct = bench.get("change_percent")
    tickers = [s["ticker"] for s in theme["stocks"]]
    changes = {t: (rows_by_ticker[t].get("price") or {}).get("change_percent") for t in tickers}
    relative = relative_rows(changes, bench_pct)

    rows = []
    for stock in theme["stocks"]:
        t = stock["ticker"]
        base = rows_by_ticker[t]
        row = dict(base, role=stock.get("role", ""), note=stock.get("note", ""),
                   relative={k: rounded(v) if isinstance(v, float) else v
                             for k, v in relative[t].items()})
        # Re-scored against peers now that the theme is known. The news is
        # cached, so this costs nothing.
        row["attention"] = compute_attention(base.get("price"), safe(news_of, t, default=[]),
                                             base.get("events"), market_pct,
                                             relative[t]["peer_median"])
        rows.append(row)
    rows.sort(key=lambda r: r["attention"]["score"], reverse=True)

    earnings_soon = []
    for row in rows:
        days = days_until_earnings(row.get("events"))
        if days is not None and 0 <= days <= 7:
            earnings_soon.append({"ticker": row["ticker"], "days": days})
    earnings_soon.sort(key=lambda e: e["days"])

    summary = theme_summary(changes, bench_pct)
    return {
        "id": theme["id"],
        "name": theme["name"],
        "description": theme.get("description", ""),
        "benchmark": {"ticker": theme["benchmark"], "change_percent": bench_pct,
                      "price": bench.get("price"), "available": bool(bench)},
        "summary": {k: rounded(v) if isinstance(v, float) else v for k, v in summary.items()},
        "earnings_soon": earnings_soon,
        "rows": rows,
    }


def compute_blocks(state: dict, selected: list[dict]) -> dict:
    """Market data for the selected themes, fetched in parallel: one quote per
    benchmark (and SPY), one row per company."""
    benchmarks = sorted({t["benchmark"] for t in selected} | {"SPY"})
    tickers = theme_store.all_tickers({"themes": selected})
    with ThreadPoolExecutor(max_workers=12) as pool:
        quotes = dict(zip(benchmarks, pool.map(lambda b: safe(price_of, b), benchmarks)))
    market_pct = (quotes.get("SPY") or {}).get("change_percent")
    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = {r["ticker"]: r for r in pool.map(lambda t: fetch_row(t, market_pct), tickers)}
    return {
        "market_change_percent": market_pct,
        "themes": [theme_block(t, rows, quotes, market_pct) for t in selected],
    }


def home_payload(state: dict) -> dict:
    return cached(f"home:{themes_key(state)}", 60, lambda: compute_blocks(state, state["themes"]))


def theme_context(state: dict, ticker: str, own_change) -> dict | None:
    """Where one company stands in its theme today, for the stock page."""
    theme = theme_store.theme_of(state, ticker)
    if theme is None:
        return None
    tickers = [s["ticker"] for s in theme["stocks"]]
    others = [t for t in tickers if t != ticker]
    wanted = others + [theme["benchmark"]]
    with ThreadPoolExecutor(max_workers=12) as pool:
        quotes = dict(zip(wanted, pool.map(lambda t: safe(price_of, t), wanted)))
    changes = {t: (quotes.get(t) or {}).get("change_percent") for t in others}
    changes[ticker] = own_change
    bench_pct = (quotes.get(theme["benchmark"]) or {}).get("change_percent")
    rel = relative_rows(changes, bench_pct)[ticker]
    return {
        "theme_id": theme["id"],
        "theme_name": theme["name"],
        "role": next((s.get("role", "") for s in theme["stocks"] if s["ticker"] == ticker), ""),
        "note": next((s.get("note", "") for s in theme["stocks"] if s["ticker"] == ticker), ""),
        "benchmark": {"ticker": theme["benchmark"], "change_percent": rounded(bench_pct)},
        **{k: rounded(v) if isinstance(v, float) else v for k, v in rel.items()},
        "peers": [{"ticker": t, "change_percent": rounded(changes[t])} for t in others],
    }


ANALYSIS_SYSTEM = """You are a market research assistant writing a short briefing on one \
stock, for a reader who can already see the price, chart, headlines and earnings date on \
screen next to what you write.

News items with source "feed" come with a short summary of the piece. Use it. The reader's \
actual problem is that there are six items and they don't want to open six tabs, so tell them \
what the coverage collectively says -- and if the pieces disagree, or one is about something \
unrelated to the price move, say that. Two articles under similar headlines often give \
different reasons, and that difference is usually the most useful thing on the page.

Items with source "search" are a headline and a publisher and nothing else: there is no \
article text behind them in your data. Report them as headlines -- what the headline itself \
says -- and say nothing about what the article reports, explains or argues beyond those words.

Write 3-4 sentences covering: how the move looks in context (including versus the market, \
if that figure is provided), what the coverage reports, set beside the move, and the next \
dated event in the data (a report date), stated as a fact.

today is the date you are writing on, and next_earnings_in_days counts from it to the report \
date in events (null when no date is known). Take any sense of how near or far a date is -- \
"reports tomorrow", "in three weeks" -- from those two, never from your own idea of the \
current date: that comes from training data that ends long before today.

vs_market in market_comparison, and vs_peers and vs_benchmark in theme_comparison, are the \
company's move minus the other one, in percentage points, already computed. Compare moves \
with those gaps -- "fell 4.2%, 3.6 points more than the market" -- and never as multiples: \
not "twice as much", "three times", "half as steep". A multiple of a small move exaggerates, \
and it would be arithmetic done in your head, where you are unreliable without knowing it.

If theme_comparison is present, use it for the context: it gives the theme's benchmark ETF, \
the median move of the company's peers in the same theme (excluding the company), and an \
attribution -- "theme" when it tracked its peers, "company" when it diverged from them \
(moved alone, against them, or held up while they fell), "mixed" in between, "quiet" when \
neither it nor its peers moved much. Say plainly whether the move looks shared with the \
theme or specific to this company, using those figures; don't recompute them. The label says \
how the moves line up, not why, so it changes nothing about the causation rule below.

Some items are videos rather than articles; their summaries are still fine to use, but \
don't describe a video as something the reader can read.

If earnings_setup is present and a report is close, say what the evidence shows about how \
this stock handles earnings -- the typical size of the move, and whether beating estimates \
has actually meant the stock rose. Where reactions carry abnormal_move, prefer it: it is the \
move beyond what the stock's market model expected given SPY that session, so it isolates \
the reaction to the report. median_abs_abnormal is its typical size and beat_but_lagged counts \
beats followed by a negative abnormal move. Never say which way it will go this time; that \
isn't knowable and stating it would be invention in a confident voice.

Stick to what you were given. Don't add background about the company from your own memory \
-- not its history, not its usual volatility, not what its products do. Your training data \
is old and the reader can't tell which half of a sentence was looked up and which half you \
recalled.

Never assert a cause you weren't given. Headlines and a price move show things happening \
together, not one causing the other: "fell 10%, which may be related to the outlook cut" -- \
never "fell 10% as/after/because the outlook was cut". The rule is about meaning, not the \
word "because". Any wording that makes the news the thing moving the price states the cause, \
and so does explaining the move through what investors or the market supposedly think: \
"suggests investors are worried that...", "the market is pricing in...", "reflects concern \
about...". Report what an item says; don't say the coverage "attributes" the move to \
something unless an item says so. Link a headline to the move only through a correlational \
connective, in every sentence that pairs them.

Rules: no buy/sell/hold recommendations, no price targets, no predictions of direction. If \
the data is thin or contradictory, say so plainly rather than filling space. No preamble, no \
headings, no bullet points."""


def ai_unavailable(what: str, exc: Exception) -> str:
    """The message shown in place of AI text that couldn't be written.

    A missing key is the common case and the SDK's own wording for it
    ("Could not resolve authentication method...") doesn't say what to do.
    """
    text = str(exc)
    if type(exc).__name__ == "AuthenticationError" or "authentication" in text.lower() \
            or "api_key" in text.lower():
        return (f"({what} needs an Anthropic API key: add ANTHROPIC_API_KEY to the .env file "
                f"and restart the app.)")
    return f"({what} is unavailable right now: {type(exc).__name__}: {text[:120]})"


def analyze(ticker: str, data: dict) -> str:
    if not data.get("price") and not data.get("news"):
        return "Not enough data available for this ticker to say anything useful."

    # The gap to the market, computed here like vs_peers and vs_benchmark,
    # so the model never compares two moves in its head. Left to itself it
    # called AMD's 4.2% fall "twice" the market's 0.6% drop.
    market = data.get("market")
    own = (data.get("price") or {}).get("change_percent")
    if market and own is not None and market.get("change_percent") is not None:
        market = dict(market, vs_market=rounded(own - market["change_percent"]))

    payload = {
        "ticker": ticker,
        # Without these the model reads next_earnings_date against its own
        # sense of "now", which is its training data's: saved eval outputs
        # called a report due tomorrow "nearly two years away". The same
        # local date days_until_earnings counts from, so the two agree.
        "today": datetime.now().date().isoformat(),
        "price": data.get("price"),
        "market_comparison": market,
        "news": data.get("news"),
        "events": data.get("events"),
        "next_earnings_in_days": days_until_earnings(data.get("events")),
        "earnings_setup": data.get("setup"),
    }
    theme = data.get("theme")
    if theme:
        payload["theme_comparison"] = {
            "theme": theme["theme_name"],
            "benchmark": theme["benchmark"],
            "peer_median_change_percent": theme["peer_median"],
            "vs_peers": theme["vs_peers"],
            "vs_benchmark": theme["vs_benchmark"],
            "attribution": theme["attribution"],
            "peers": theme["peers"],
        }
    content = json.dumps(payload, indent=2, default=str)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=350,
            system=ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return ai_unavailable("The analysis", exc)
    return without_multiples(content, text)


REWRITE_MULTIPLE = (
    'This sentence states one move as a multiple of another: "{sentence}" Rewrite the briefing '
    "so that moves are compared only by the gaps in points the data gives (vs_market, vs_peers, "
    "vs_benchmark) or by their own percentages. Keep everything else as it was, and reply with "
    "the briefing only."
)


def without_multiples(content: str, text: str) -> str:
    """The analysis, with a move stated as a multiple of another rewritten.

    The prompt forbids multiples, and that held in about 1% of analyses
    until a change left the model less news to write about; then it leaked
    in 3 of 40. So the code checks, with the patterns the evals use
    (guards.py), and asks once for a rewrite, quoting the sentence. If the
    rewrite still has one, or the call fails, the first text stands: an
    analysis with a multiple is better than none, and the evals count it.
    """
    match = find_multiple(text)
    if match is None:
        return text
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=350,
            system=ANALYSIS_SYSTEM,
            messages=[
                {"role": "user", "content": content},
                {"role": "assistant", "content": text},
                {"role": "user", "content": REWRITE_MULTIPLE.format(
                    sentence=sentence_around(text, match))},
            ],
        )
        rewrite = "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception:
        return text
    return rewrite if rewrite and find_multiple(rewrite) is None else text


# --- routes -----------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/overview")
def overview():
    def produce():
        with ThreadPoolExecutor(max_workers=4) as pool:
            quotes = list(pool.map(lambda pair: index_quote(*pair), INDICES))
        history = safe(history_of, "SPY", default=[]) or []
        return {
            "indices": quotes,
            "market": market_status(),
            # The session the latest prices come from. Before the open on a
            # Monday that's Friday's, and the pages say so instead of
            # calling Friday's move "today".
            "last_session": history[-1]["date"] if history else None,
            "today": datetime.now(ZoneInfo("America/New_York")).date().isoformat(),
        }

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


@app.route("/api/home")
def home_route():
    return jsonify(home_payload(load_themes()))


@app.route("/api/theme/<theme_id>")
def theme_route(theme_id: str):
    state = load_themes()
    try:
        theme = theme_store.find_theme(state, theme_id)
    except ThemeError as exc:
        return jsonify({"error": str(exc)}), 404
    payload = cached(f"theme:{theme_id}:{themes_key(state)}", 60,
                     lambda: compute_blocks(state, [theme]))
    return jsonify({"market_change_percent": payload["market_change_percent"],
                    **payload["themes"][0]})


# --- theme tabs: performance, earnings, peers -------------------------
# The theme page's deeper layers. Each is its own endpoint so a tab only
# costs what it shows, and each is cached on the slower clock its data
# changes on.
PERIOD_ORDER = ["1M", "3M", "6M", "YTD", "1Y"]


def _round_all(d: dict) -> dict:
    return {k: rounded(v) if isinstance(v, float) else v for k, v in d.items()}


def theme_performance(theme: dict) -> dict:
    """Returns over several windows, each against the ETF and the peers.

    The same leave-one-out comparison as the daily view, applied to each
    window's returns: a company up 40% in three months means one thing if
    its peers are up 38% and another if they're flat.
    """
    tickers = [s["ticker"] for s in theme["stocks"]]
    wanted = tickers + [theme["benchmark"]]
    with ThreadPoolExecutor(max_workers=12) as pool:
        series = dict(zip(wanted, pool.map(lambda t: safe(closes_of, t), wanted)))
    returns = {t: performance.period_returns(s) if s is not None and len(s) else {}
               for t, s in series.items()}
    bench = returns.get(theme["benchmark"], {})

    by_period, summaries = {}, {}
    for period in PERIOD_ORDER:
        changes = {t: returns[t].get(period) for t in tickers}
        by_period[period] = relative_rows(changes, bench.get(period))
        summaries[period] = _round_all(theme_summary(changes, bench.get(period)))

    rows = []
    for stock in theme["stocks"]:
        t = stock["ticker"]
        rows.append({
            "ticker": t,
            "role": stock.get("role", ""),
            "periods": {p: _round_all({"return": returns[t].get(p), **by_period[p][t]})
                        for p in PERIOD_ORDER},
        })
    return {
        "id": theme["id"], "name": theme["name"], "periods": PERIOD_ORDER,
        "benchmark": {"ticker": theme["benchmark"],
                      "returns": {p: rounded(bench.get(p)) for p in PERIOD_ORDER}},
        "summary": summaries,
        "rows": rows,
    }


def theme_earnings(theme: dict) -> dict:
    """Each company's recent reactions measured against its market model,
    and whether, across the theme, bigger surprises met bigger reactions."""
    tickers = [s["ticker"] for s in theme["stocks"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        setups = dict(zip(tickers, pool.map(lambda t: safe(setup_of, t, default={}), tickers)))
        events = dict(zip(tickers, pool.map(lambda t: safe(events_of, t, default={}), tickers)))

    rows, points = [], []
    for t in tickers:
        setup = setups.get(t) or {}
        reactions = setup.get("reactions") or []
        modelled = [r for r in reactions if r.get("abnormal_move") is not None]
        for r in modelled:
            if r.get("surprise_percent") is not None:
                points.append({"ticker": t, "date": r["date"], "surprise": r["surprise_percent"],
                               "abnormal": r["abnormal_move"], "standardized": r["standardized"]})
        days = days_until_earnings(events.get(t))
        rows.append({
            "ticker": t,
            "next_report_days": days if days is not None and days >= 0 else None,
            "latest": modelled[0] if modelled else (reactions[0] if reactions else None),
            "reports": len(reactions),
            "modelled": len(modelled),
            "median_abs_abnormal": setup.get("median_abs_abnormal"),
            "beat_count": setup.get("beat_count"),
            "beat_but_lagged": setup.get("beat_but_lagged"),
            "unusual_count": setup.get("unusual_count"),
            "unavailable_reason": setup.get("unavailable_reason"),
        })
    rows.sort(key=lambda r: (r["next_report_days"] is None, r["next_report_days"] or 0))

    beats = [p for p in points if p["surprise"] > 0]
    misses = [p for p in points if p["surprise"] < 0]
    correlation = performance.rank_correlation([p["surprise"] for p in points],
                                               [p["abnormal"] for p in points])
    return {
        "id": theme["id"], "name": theme["name"],
        "rows": rows,
        "points": points,
        "stats": {
            "reports": len(points),
            "beats": len(beats),
            "beats_rewarded": sum(1 for p in beats if p["abnormal"] > 0),
            "misses": len(misses),
            "misses_punished": sum(1 for p in misses if p["abnormal"] < 0),
            "rank_correlation": rounded(correlation),
            "min_points": performance.MIN_CORRELATION_POINTS,
        },
    }


# Shown beside a figure when the number on its own would mislead. The rules
# live with the figures (tools/fundamentals.py) so the agent sees them too.
def peer_flags(stats: dict) -> list[str]:
    return figure_caveats(stats)


PEER_METRICS = [
    # key, label, unit
    ("market_cap", "Market cap", "money"),
    ("forward_pe", "Forward P/E", "x"),
    ("ev_to_sales", "EV / sales", "x"),
    ("revenue_growth_percent", "Revenue growth", "%"),
    ("gross_margin_percent", "Gross margin", "%"),
    ("operating_margin_percent", "Operating margin, qtr", "%"),
    ("estimate_change_90d", "EPS estimate, 90d", "%"),
    ("net_revisions_30d", "Net revisions, 30d", "count"),
]


def theme_peers(theme: dict) -> dict:
    tickers = [s["ticker"] for s in theme["stocks"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        stats = dict(zip(tickers, pool.map(lambda t: safe(stats_of, t, default={}), tickers)))
        revisions = dict(zip(tickers, pool.map(lambda t: safe(revisions_of, t, default={}), tickers)))

    rows = []
    for stock in theme["stocks"]:
        t = stock["ticker"]
        s, r = stats.get(t) or {}, revisions.get(t) or {}
        up, down = r.get("up_30d"), r.get("down_30d")
        values = {
            **{k: s.get(k) for k, _, _ in PEER_METRICS if k in s},
            "estimate_change_90d": r.get("change_90d_percent"),
            "net_revisions_30d": None if up is None or down is None else up - down,
        }
        rows.append({"ticker": t, "name": s.get("name"), "role": stock.get("role", ""),
                     "values": _round_all(values), "revisions": r,
                     "analysts": s.get("analysts"), "flags": peer_flags(s)})

    medians = {}
    for key, _, _ in PEER_METRICS:
        present = sorted(row["values"].get(key) for row in rows if row["values"].get(key) is not None)
        if present:
            mid = len(present) // 2
            medians[key] = rounded(present[mid] if len(present) % 2
                                   else (present[mid - 1] + present[mid]) / 2)
    return {"id": theme["id"], "name": theme["name"],
            "metrics": [{"key": k, "label": label, "unit": unit} for k, label, unit in PEER_METRICS],
            "rows": rows, "medians": medians}


def _theme_tab(theme_id: str, kind: str, builder, ttl: int):
    state = load_themes()
    try:
        theme = theme_store.find_theme(state, theme_id)
    except ThemeError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(cached(f"theme-{kind}:{theme_id}:{themes_key(state)}", ttl, lambda: builder(theme)))


@app.route("/api/theme/<theme_id>/performance")
def theme_performance_route(theme_id: str):
    return _theme_tab(theme_id, "performance", theme_performance, TTL["history"])


@app.route("/api/theme/<theme_id>/earnings")
def theme_earnings_route(theme_id: str):
    return _theme_tab(theme_id, "earnings", theme_earnings, SLOW_TTL)


@app.route("/api/theme/<theme_id>/peers")
def theme_peers_route(theme_id: str):
    return _theme_tab(theme_id, "peers", theme_peers, SLOW_TTL)


# --- theme management -------------------------------------------------
def themes_config(state: dict) -> dict:
    return {
        "themes": state["themes"],
        "limits": {"themes": theme_store.MAX_THEMES,
                   "stocks_per_theme": theme_store.MAX_STOCKS_PER_THEME,
                   "stocks_for_peers": theme_store.MIN_STOCKS_FOR_PEERS},
    }


def resolves(ticker: str) -> bool:
    """Whether Yahoo has a price for this ticker -- checked before saving,
    so a typo never becomes a permanently empty row."""
    return safe(price_of, ticker) is not None


def change_themes(apply) -> tuple:
    """Load, apply one change, save -- under a lock, so two quick edits
    from the page can't overwrite each other."""
    with _themes_lock:
        state = load_themes()
        try:
            apply(state)
        except ThemeError as exc:
            return jsonify({"error": str(exc)}), 400
        save_themes(state)
        return jsonify(themes_config(state)), 200


@app.route("/api/themes", methods=["GET"])
def list_themes_route():
    return jsonify(themes_config(load_themes()))


@app.route("/api/themes", methods=["POST"])
def create_theme_route():
    body = request.get_json(force=True, silent=True) or {}
    benchmark = (body.get("benchmark") or "SPY").strip().upper()
    if not resolves(benchmark):
        return jsonify({"error": f"No market data for benchmark '{benchmark}'. Use an ETF "
                                 f"ticker, e.g. SMH or QQQ."}), 400
    return change_themes(lambda s: theme_store.create_theme(
        s, body.get("name"), benchmark, body.get("description", "")))


@app.route("/api/themes/<theme_id>", methods=["PATCH"])
def update_theme_route(theme_id: str):
    body = request.get_json(force=True, silent=True) or {}
    benchmark = body.get("benchmark")
    if benchmark is not None and not resolves(str(benchmark).strip().upper()):
        return jsonify({"error": f"No market data for benchmark '{benchmark}'."}), 400
    return change_themes(lambda s: theme_store.update_theme(
        s, theme_id, name=body.get("name"), benchmark=benchmark,
        description=body.get("description")))


@app.route("/api/themes/<theme_id>", methods=["DELETE"])
def delete_theme_route(theme_id: str):
    return change_themes(lambda s: theme_store.delete_theme(s, theme_id))


@app.route("/api/themes/<theme_id>/stocks", methods=["POST"])
def add_stock_route(theme_id: str):
    body = request.get_json(force=True, silent=True) or {}
    ticker = str(body.get("ticker") or "").strip().upper()
    try:
        ticker = theme_store.clean_ticker(ticker)
    except ThemeError as exc:
        return jsonify({"error": str(exc)}), 400
    if not resolves(ticker):
        return jsonify({"error": f"No market data for '{ticker}'. Check the symbol."}), 400
    return change_themes(lambda s: theme_store.add_stock(s, theme_id, ticker, body.get("note", "")))


@app.route("/api/themes/<theme_id>/stocks/<ticker>", methods=["PATCH"])
def update_stock_route(theme_id: str, ticker: str):
    body = request.get_json(force=True, silent=True) or {}
    return change_themes(lambda s: theme_store.update_stock(
        s, theme_id, ticker, note=body.get("note"), move_to=body.get("move_to")))


@app.route("/api/themes/<theme_id>/stocks/<ticker>", methods=["DELETE"])
def remove_stock_route(theme_id: str, ticker: str):
    return change_themes(lambda s: theme_store.remove_stock(s, theme_id, ticker))


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
            "stats": lambda: stats_of(ticker),
            "setup": lambda: setup_of(ticker),
            "revisions": lambda: revisions_of(ticker),
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
        data.setdefault("revisions", {})

        market_pct = data.pop("spy", None)
        data["market"] = {"ticker": "SPY", "change_percent": market_pct} if market_pct is not None else None
        own = (data.get("price") or {}).get("change_percent")
        data["theme"] = safe(theme_context, state, ticker, own)
        data["flags"] = peer_flags(data.get("stats") or {})
        data["attention"] = compute_attention(
            data.get("price"), data.get("news"), data.get("events"), market_pct,
            (data["theme"] or {}).get("peer_median"),
        )
        data["analysis"] = analyze(ticker, data)
        return data

    state = load_themes()
    return jsonify(cached(f"stock:{ticker}:{themes_key(state)}", 120, produce))


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
4. Earnings in the next week: upcoming_reports lists every known report on the watchlist, \
soonest first, with its date and the days until it. When you say which company reports next, \
or when one reports, take it from that list -- don't work it out from the names, and don't \
convert days into dates yourself. Each name also carries next_earnings_in_days (null when no \
date is known). If none falls within seven days, one short sentence saying so is \
enough, or leave it out -- don't put a judgement about what kind of week it is in its place.

The watchlist is a list of names the reader is TRACKING. It is not a portfolio and this app
has no holdings data, so never write "you own", "your holdings" or "your position" -- write
"on your watchlist" or "you're tracking".

If the watchlist arrives grouped into themes, each theme is a set of companies sharing a \
driver, with a benchmark ETF. Every name carries its peers' median move -- the other \
companies in the same theme, excluding itself -- and a move_type: "theme" when it tracked its \
peers, "company" when it diverged from them (moved alone, against them, or held up while they \
fell), "mixed" in between, "quiet" when neither it nor its peers moved much. Use \
these figures; don't recompute them. A name moving with its whole theme is part of one theme \
story, so tell that story once, at the theme level. A name moving against its peers or well \
beyond them is a company-specific story worth naming. These labels say how moves line up, \
not why -- the rule on causation below still applies.

If it's a quiet day, say so in a line rather than inflating it -- that's useful too.

Three or four short paragraphs. No headings, no bullet points, no preamble.

HARD RULES

No trading advice: no buy/sell/hold, no price targets, no predictions about which way a \
price will go.

No posture advice. Don't tell the reader how to be positioned, even without naming a \
trade: not "a day for caution", not "this is about preservation, not action", not "steady \
as it goes", not "sit tight", not "if you've been watching from the sidelines". Whether to \
hold, trim, add or do nothing is entirely theirs.

Posture advice mostly turns up in two places. One is the closing line: a verdict on what \
kind of day or week this is for the reader ("a quiet week to let things play out", "a day for \
watching, not doing"). The other is a conditional about the reader ("if you're following this \
space...", "if any of these matter to you"). So end on the last fact you have -- the next \
scheduled event, or the last notable move -- and describe the market, not the reader.

But DO tell them what to pay attention to -- that is the whole job. "NVDA reports \
Wednesday", "the one headline that matters today is X", "worth watching whether the export \
rules get clarified", "that's the next scheduled event on this list" are all correct and \
wanted. The line is ATTENTION versus POSITION: what to look at is yours to say, what to do \
with their money is not.

State calendar facts directly, and only the ones the data contains. "NVDA reports in three \
days" -- not "if you're watching for catalysts, NVDA's report is the one to mark", which says \
the same thing while telling them what to do about it. A null next_earnings_in_days means no \
date is known, not that nothing is scheduled: don't turn unknown dates into an empty calendar.

Name companies by ticker symbol -- NVDA, not Nvidia -- since that is how they appear on \
screen beside what you write.

Never assert a cause you were not given. You get headlines and price moves, which show \
things happening together, not one causing the other. Write "fell 8%, which may be \
related to the export rules reported this morning". Never "fell 8% as/after/because the \
export rules widened" -- those state the link as established fact, and you don't know it.

That rule is about meaning, not about the word "because". Any wording that makes a \
headline the thing moving prices states the cause: "on news that...", "following a report \
that...", "is driving...", "the driver", "the story behind the drop", "weighing on", "sent \
shares lower". When a sentence puts a headline beside a move, join the two only with a \
correlational link -- "alongside", "coincided with", "may be related to" -- and do it in \
every such sentence: a hedge in one sentence doesn't cover the next.

Stick to the data you were handed. Don't add specifics about the event from your own \
memory: your training data is old, and an invented detail is worse than a missing one."""


def _brief_name(r: dict) -> dict:
    return {
        "ticker": r["ticker"],
        "change_percent": rounded((r.get("price") or {}).get("change_percent")),
        "attention": (r.get("attention") or {}).get("level"),
        "reasons": [f["label"] for f in (r.get("attention") or {}).get("factors", [])],
        "top_headline": r.get("top_headline"),
        # Explicit so a calendar claim can be checked: the brief used to
        # see a report date only as an attention reason, so "nothing
        # reports this week" was never supported by its input.
        "next_earnings_in_days": days_until_earnings(r.get("events")),
    }


def build_brief(rows: list[dict], market_pct, indices: list[dict],
                movers: list[dict], headlines: list[dict], themes: list[dict] | None = None) -> str:
    """One Claude call covering the watchlist AND the wider market.

    With `themes` (the home page's theme blocks), the watchlist goes in
    grouped by theme, each name carrying its peer comparison. Without it --
    as in the evals' fixed scenarios -- it goes in as one flat list.

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
    }
    if themes:
        payload["watchlist_themes"] = [
            {
                "theme": b["name"],
                "benchmark": {"ticker": b["benchmark"]["ticker"],
                              "change_percent": rounded(b["benchmark"]["change_percent"])},
                "theme_average_change_percent": b["summary"]["average"],
                "names_beating_benchmark": (
                    f"{b['summary']['beat_count']} of {b['summary']['count']}"
                    if b["summary"]["beat_count"] is not None else None),
                "names": [
                    dict(_brief_name(r),
                         peer_median_change_percent=r["relative"]["peer_median"],
                         move_type=r["relative"]["attribution"])
                    for r in b["rows"]
                ],
            }
            for b in themes
        ]
    else:
        payload["watchlist"] = [_brief_name(r) for r in rows]
    # Sorted here, not left to the model: asked to find the soonest among
    # nineteen names spread over four themes, it named VRT and TSLA (16 days)
    # as the next to report when TSM, last in its theme, reported in 10.
    # Every report, not the first few: a cut-off of six fell inside a group
    # reporting the same day, and the brief then grouped the calendar wrongly.
    # The date is given so the model never converts days to dates (it turned
    # "in 22 days" into "January 27th").
    upcoming = []
    for r in rows:
        days = days_until_earnings(r.get("events"))
        if days is not None and days >= 0:
            when = str((r.get("events") or {}).get("next_earnings_date"))[:10]
            upcoming.append({"ticker": r["ticker"], "date": when, "days": days})
    payload["upcoming_reports"] = sorted(upcoming, key=lambda e: (e["days"], e["ticker"]))
    payload.update({
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
    })

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=BRIEF_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2, default=str)}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()
    except Exception as exc:
        return ai_unavailable("The AI brief", exc)


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
    state = load_themes()
    tickers = theme_store.all_tickers(state)
    theme_names = {s["ticker"]: t["name"] for t in state["themes"] for s in t["stocks"]}

    def produce():
        with ThreadPoolExecutor(max_workers=12) as pool:
            items = list(pool.map(get_earnings_schedule, tickers))
        for item in items:
            item["theme"] = theme_names.get(item.get("ticker"))

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
    state = load_themes()
    tickers = theme_store.all_tickers(state)

    def produce():
        # The same theme blocks the home page shows, so the brief and the
        # cards beneath it are written from identical numbers.
        home = home_payload(state)
        market_pct = home["market_change_percent"]
        blocks = home["themes"]
        rows = [r for b in blocks for r in b["rows"]]

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
            "brief": build_brief(rows, market_pct, indices, movers, headlines, themes=blocks),
            "generated_at": datetime.now(ZoneInfo("America/New_York")).strftime("%I:%M %p ET").lstrip("0"),
            "scanned_market": len(movers),
        }

    # 15 minutes: regenerating on every page load burns tokens to say the
    # same thing. The Refresh button sends ?t=..., which drops the cached
    # brief -- before, it only defeated the browser's cache, so the button
    # returned the same brief for up to 15 minutes.
    key = f"brief:{themes_key(state)}"
    if request.args.get("t"):
        _cache.pop(key, None)
    return jsonify(cached(key, 900, produce))


@app.route("/api/discover")
def discover_route():
    watching = load_watchlist()

    def produce():
        return discover_payload()

    return jsonify(cached("discover:" + ",".join(watching), 600, produce))


if __name__ == "__main__":
    print("\nMarket Agent -- open http://127.0.0.1:5050 in your browser\n")
    app.run(debug=True, port=5050)
