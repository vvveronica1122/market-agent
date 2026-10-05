"""
Market data tools for the agent.

These are plain Python functions with no dependency on the LLM at all --
they're the "hands" the agent can use. Keeping them separate and testable
like this is a core agent-building best practice: you want to be able to
verify each tool works correctly on its own, before trusting an LLM to
decide when to call it.

Data comes from Yahoo Finance via the `yfinance` package, which needs no
API key.
"""

from __future__ import annotations

import html
import re
from typing import Any


def _plain_text(value: str | None) -> str:
    """Strip markup and decode entities.

    Yahoo's `description` is HTML while `summary` is plain, but the fields
    are inconsistent across items, so anything used as text goes through
    here rather than trusting which one arrived.
    """
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

import yfinance as yf


def get_stock_price(ticker: str) -> dict[str, Any]:
    """Get the latest price snapshot for a ticker.

    Returns a dict with price, currency, day change, and percent change.
    Raises ValueError if the ticker doesn't resolve to any data.
    """
    t = yf.Ticker(ticker)
    try:
        fast = t.fast_info
        price = fast["lastPrice"]
        prev_close = fast["previousClose"]
        currency = fast.get("currency", "USD") if hasattr(fast, "get") else "USD"
    except Exception as exc:
        raise ValueError(f"Could not fetch price data for '{ticker}': {exc}") from exc

    if price is None:
        raise ValueError(f"No price data found for ticker '{ticker}'. Check the symbol is correct.")

    change = None
    change_percent = None
    if prev_close:
        change = round(price - prev_close, 2)
        change_percent = round((change / prev_close) * 100, 2)

    return {
        "ticker": ticker.upper(),
        "price": round(price, 2),
        "currency": currency or "USD",
        "previous_close": round(prev_close, 2) if prev_close else None,
        "change": change,
        "change_percent": change_percent,
    }


def get_recent_news(ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    """Get recent news headlines related to a ticker.

    Returns title, publisher, link, published time, a short summary, and
    the content type.

    The summary matters more than it looks. Without it, anything built on
    top of this is summarising HEADLINES -- which cannot distinguish two
    articles that share a headline but disagree on the reason. Yahoo
    supplies a couple of hundred characters of real summary text per item
    and the first version of this function discarded it.

    content_type is carried because a meaningful share of these are VIDEO,
    and telling someone "here's a summary" of something they can only
    watch is a small lie worth avoiding.

    Returns an empty list (not an error) if no news is found -- the agent
    should treat that as "nothing notable right now", not a failure.

    When the ticker's own feed is empty, Yahoo's search endpoint is tried;
    see _search_news.
    """
    t = yf.Ticker(ticker)
    try:
        raw_items = t.news or []
    except Exception:
        raw_items = []
    if not raw_items:
        raw_items = _search_news(ticker, limit)

    items: list[dict[str, Any]] = []
    for entry in raw_items[:limit]:
        # yfinance has changed its news payload shape across versions;
        # this handles both the flat and the nested "content" formats.
        content = entry.get("content", entry)
        title = content.get("title") or entry.get("title")
        publisher = (
            (content.get("provider") or {}).get("displayName")
            or entry.get("publisher")
        )
        link = (
            (content.get("clickThroughUrl") or {}).get("url")
            or (content.get("canonicalUrl") or {}).get("url")
            or entry.get("link")
        )
        published = content.get("pubDate") or entry.get("providerPublishTime")

        if not title:
            continue

        summary = _plain_text(content.get("summary")) or _plain_text(content.get("description"))
        content_type = (content.get("contentType") or entry.get("type") or "").upper()

        items.append(
            {
                "title": title,
                "publisher": publisher or "Unknown",
                "link": link,
                "published": published,
                "summary": summary,
                "content_type": content_type or "STORY",
                "is_video": content_type == "VIDEO",
            }
        )

    return items


# Share classes Yahoo tags under one symbol: Alphabet stories carry GOOG
# even when the search was for GOOGL, which left GOOGL with no news at all.
SAME_COMPANY = {"GOOGL": {"GOOG"}, "GOOG": {"GOOGL"}, "FOXA": {"FOX"}, "FOX": {"FOXA"},
                "NWSA": {"NWS"}, "NWS": {"NWSA"}, "BRK-B": {"BRK-A"}, "BRK-A": {"BRK-B"}}


def _search_news(ticker: str, limit: int) -> list[dict[str, Any]]:
    """Stories from Yahoo's search endpoint, as a fallback.

    In October 2026 every ticker's own news feed came back empty while
    search still returned current stories, so the dashboard showed
    "No recent headlines" everywhere and news never counted towards a rank.
    Search matches text, so only stories Yahoo tags with this ticker are
    kept. They come in the flat format: a headline and publisher, no summary.
    """
    try:
        found = yf.Search(ticker, max_results=1, news_count=limit * 2).news or []
    except Exception:
        return []
    symbols = {ticker.upper()} | SAME_COMPANY.get(ticker.upper(), set())
    return [item for item in found if symbols & set(item.get("relatedTickers") or [])]


def get_upcoming_events(ticker: str) -> dict[str, Any]:
    """Get upcoming events for a ticker: next earnings date and ex-dividend date.

    Fields are None when yfinance has no data for that field -- that's
    normal (not every company has an upcoming dividend, for instance).
    """
    t = yf.Ticker(ticker)
    result: dict[str, Any] = {
        "ticker": ticker.upper(),
        "next_earnings_date": None,
        "ex_dividend_date": None,
    }

    try:
        cal = t.calendar
        if isinstance(cal, dict):
            earnings = cal.get("Earnings Date")
            if isinstance(earnings, list) and earnings:
                result["next_earnings_date"] = str(earnings[0])
            ex_div = cal.get("Ex-Dividend Date")
            if ex_div:
                result["ex_dividend_date"] = str(ex_div)
    except Exception:
        pass

    return result


def get_price_history(ticker: str, period: str = "1mo") -> list[dict[str, Any]]:
    """Get a short daily closing-price history for a ticker, used for trend charts.

    Returns a list of {"date": "YYYY-MM-DD", "close": float} points, oldest
    first. Returns an empty list (not an error) if no history is available.
    """
    t = yf.Ticker(ticker)
    try:
        hist = t.history(period=period)
    except Exception as exc:
        raise ValueError(f"Could not fetch price history for '{ticker}': {exc}") from exc

    if hist is None or hist.empty:
        return []

    points: list[dict[str, Any]] = []
    for idx, row in hist.iterrows():
        close = row.get("Close")
        if close is None:
            continue
        points.append({"date": idx.strftime("%Y-%m-%d"), "close": round(float(close), 2)})
    return points
