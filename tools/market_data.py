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

from typing import Any

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

    Returns a list of dicts with title, publisher, link, and published time.
    Returns an empty list (not an error) if no news is found -- the agent
    should treat that as "nothing notable right now", not a failure.
    """
    t = yf.Ticker(ticker)
    try:
        raw_items = t.news or []
    except Exception:
        raw_items = []

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

        items.append(
            {
                "title": title,
                "publisher": publisher or "Unknown",
                "link": link,
                "published": published,
            }
        )

    return items


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
