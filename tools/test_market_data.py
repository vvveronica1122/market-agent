"""
Tests for parsing Yahoo's news payloads, with yfinance stubbed out.
Free, offline, instant.

Yahoo has served news in two shapes (flat, and nested under "content"), and
in October 2026 the per-ticker feed went empty while search kept working.
These check both shapes parse, and that the search fallback only keeps
stories tagged with the ticker asked about.

    python3 tools/test_market_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import market_data


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


NESTED = {"content": {"title": "Micron raises guidance", "provider": {"displayName": "Wire"},
                      "canonicalUrl": {"url": "https://example.com/a"}, "pubDate": "2026-10-05T12:00:00Z",
                      "summary": "<p>Micron raised its outlook.</p>", "contentType": "STORY"}}
FLAT_TAGGED = {"title": "Micron stock drops amid fears", "publisher": "Barrons.com",
               "link": "https://example.com/b", "providerPublishTime": 1791222300,
               "type": "STORY", "relatedTickers": ["MU"]}
FLAT_OTHER = {"title": "Nasdaq eyes a record", "publisher": "Barrons.com", "link": "https://example.com/c",
              "providerPublishTime": 1791223082, "type": "STORY", "relatedTickers": ["^IXIC", "MUX"]}


class FakeTicker:
    feed: list = []

    def __init__(self, ticker):
        self.ticker = ticker

    @property
    def news(self):
        return self.feed


class FakeSearch:
    results: list = []
    calls: list = []

    def __init__(self, query, **kwargs):
        FakeSearch.calls.append(query)
        self.news = self.results


def main() -> int:
    failures = 0
    real_ticker, real_search = market_data.yf.Ticker, market_data.yf.Search
    market_data.yf.Ticker, market_data.yf.Search = FakeTicker, FakeSearch
    try:
        print("\nThe ticker's own feed")
        FakeTicker.feed = [NESTED]
        items = market_data.get_recent_news("MU")
        failures += not check("the nested format parses, summary as plain text",
                              items and items[0]["title"] == "Micron raises guidance"
                              and items[0]["summary"] == "Micron raised its outlook."
                              and items[0]["publisher"] == "Wire", str(items))
        failures += not check("search isn't asked when the feed has stories", not FakeSearch.calls)

        print("\nThe search fallback")
        FakeTicker.feed = []
        FakeSearch.results = [FLAT_OTHER, FLAT_TAGGED]
        items = market_data.get_recent_news("mu")
        failures += not check("an empty feed falls back to search", FakeSearch.calls == ["mu"])
        failures += not check("only stories tagged with the ticker are kept (not MUX, not the index)",
                              [i["title"] for i in items] == ["Micron stock drops amid fears"], str(items))
        failures += not check("the flat format parses, with no invented summary",
                              items and items[0]["publisher"] == "Barrons.com" and not items[0]["summary"]
                              and items[0]["link"] == "https://example.com/b", str(items))
        FakeSearch.results = [dict(FLAT_TAGGED, type="VIDEO")]
        items = market_data.get_recent_news("MU")
        failures += not check("a flat-format video is marked as one", items and items[0]["is_video"], str(items))

        FakeSearch.results = [dict(FLAT_TAGGED, relatedTickers=["GOOG", "META"])]
        failures += not check("a story tagged with the other share class counts (GOOG for GOOGL)",
                              len(market_data.get_recent_news("GOOGL")) == 1)

        class Broken:
            def __init__(self, *a, **k):
                raise RuntimeError("search is down")
        market_data.yf.Search = Broken
        failures += not check("a failing search means no news, not an error",
                              market_data.get_recent_news("MU") == [])
    finally:
        market_data.yf.Ticker, market_data.yf.Search = real_ticker, real_search

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
