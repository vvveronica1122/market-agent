"""
Market-wide scanning tools.

The difference between this and market_data.py matters. market_data.py
answers "tell me about THIS ticker" -- you have to already know what
you're asking about. This module answers "what is the market doing right
now", without being told where to look. That's what makes genuine
discovery possible instead of just monitoring a list you already chose.

It uses Yahoo's screener endpoint through yfinance, which returns a whole
ranked set in ONE request -- far better than fetching tickers one at a
time. The predefined screens also come with sensible quality filters
already applied (market cap over $2B, price over $5, real volume), which
keeps the results free of the microcap pumps that would otherwise
dominate any "biggest movers today" list.
"""

from __future__ import annotations

from typing import Any

import yfinance as yf

# Screens worth scanning. Gainers and losers find today's outliers;
# most_actives catches names with unusual attention that may not have
# moved much in price yet.
DEFAULT_SCREENS = ("day_gainers", "day_losers", "most_actives")

MIN_MARKET_CAP = 2_000_000_000
MIN_PRICE = 5.0


def _num(value: Any) -> float | None:
    """Yahoo sometimes returns bare numbers and sometimes {'raw': n, 'fmt': str}."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("raw")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_market_movers(screens: tuple[str, ...] = DEFAULT_SCREENS, per_screen: int = 25) -> list[dict]:
    """Scan the market for notable names today.

    Returns a de-duplicated list of dicts. A ticker appearing in more than
    one screen keeps a record of which ones, in `screens` -- a stock that
    is both a big loser AND unusually active is more interesting than one
    that is merely a big loser.

    A failing screen is skipped rather than raised: partial results are
    far more useful here than none.
    """
    found: dict[str, dict] = {}

    for screen_name in screens:
        try:
            payload = yf.screen(screen_name, count=per_screen)
        except Exception:
            continue

        for quote in (payload or {}).get("quotes", []) or []:
            symbol = quote.get("symbol")
            if not symbol:
                continue

            if symbol in found:
                found[symbol]["screens"].append(screen_name)
                continue

            found[symbol] = {
                "ticker": symbol,
                "name": quote.get("shortName") or quote.get("longName") or symbol,
                "price": _num(quote.get("regularMarketPrice")),
                "change_percent": _num(quote.get("regularMarketChangePercent")),
                "volume": _num(quote.get("regularMarketVolume")),
                "market_cap": _num(quote.get("marketCap")),
                "screens": [screen_name],
            }

    return list(found.values())


def filter_quality(movers: list[dict], exclude: set[str] | None = None) -> list[dict]:
    """Drop names that are too small, too cheap, or already being watched.

    Yahoo's predefined screens apply most of this already, but a custom
    query or a changed endpoint shouldn't be able to flood the UI with
    penny stocks, so the floor is enforced here too.
    """
    exclude = exclude or set()
    keep = []
    for m in movers:
        if m["ticker"] in exclude:
            continue
        if m.get("change_percent") is None:
            continue
        if (m.get("market_cap") or 0) < MIN_MARKET_CAP:
            continue
        if (m.get("price") or 0) < MIN_PRICE:
            continue
        keep.append(m)
    return keep


def get_market_news(queries: tuple[str, ...] = ("stock market", "stocks earnings"),
                    per_query: int = 10) -> list[dict]:
    """Broad market headlines, not tied to any one ticker.

    Used to give the brief awareness of things that don't show up as a
    price move on the watchlist -- macro data, policy, sector stories.
    """
    items: list[dict] = []
    seen_titles: set[str] = set()

    for query in queries:
        try:
            results = yf.Search(query, news_count=per_query, max_results=1,
                                raise_errors=False).news or []
        except Exception:
            continue

        for entry in results:
            # Same version-shape problem as market_data.get_recent_news.
            content = entry.get("content", entry)
            title = content.get("title") or entry.get("title")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)

            publisher = (
                (content.get("provider") or {}).get("displayName")
                or entry.get("publisher")
                or "Unknown"
            )
            link = (
                (content.get("clickThroughUrl") or {}).get("url")
                or (content.get("canonicalUrl") or {}).get("url")
                or entry.get("link")
            )
            items.append(
                {
                    "title": title,
                    "publisher": publisher,
                    "link": link,
                    "related_tickers": entry.get("relatedTickers") or [],
                }
            )

    return items
