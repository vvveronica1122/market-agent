"""
Tests for the dashboard server, with the market data layer stubbed out.

Why stub? Two reasons, and both are general lessons:

1. Tests that call a live API are slow and flaky -- they fail when Yahoo
   is down or rate-limits you, which tells you nothing about your code.
2. Stubbing lets us feed in *exact* scenarios (a stock down 6% with
   earnings in 3 days) and assert the ranking logic responds correctly.
   You can't arrange that with live data.

Nothing here calls Anthropic or the network. Run it with:

    python3 web/test_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app as server  # noqa: E402


# --- fake data -------------------------------------------------------
def fake_price(ticker):
    table = {
        "CRASH": {"ticker": "CRASH", "price": 100.0, "currency": "USD",
                  "previous_close": 106.4, "change": -6.4, "change_percent": -6.0},
        "QUIET": {"ticker": "QUIET", "price": 50.0, "currency": "USD",
                  "previous_close": 49.95, "change": 0.05, "change_percent": 0.1},
        # not on the watchlist -- this is what Discover should surface
        "SURGE": {"ticker": "SURGE", "price": 88.0, "currency": "USD",
                  "previous_close": 82.2, "change": 5.8, "change_percent": 7.1},
        "SPY": {"ticker": "SPY", "price": 500.0, "currency": "USD",
                "previous_close": 499.0, "change": 1.0, "change_percent": 0.2},
    }
    if ticker not in table:
        raise ValueError(f"No price data found for ticker '{ticker}'.")
    return table[ticker]


KNOWN = {"CRASH", "QUIET", "SPY", "SURGE"}


def fake_history(ticker, period="1mo"):
    # Mirror the real thing: an unknown ticker fails here too, so the
    # degradation test exercises a realistic scenario.
    if ticker not in KNOWN:
        raise ValueError(f"Could not fetch price history for '{ticker}'.")
    return [{"date": f"2026-09-{d:02d}", "close": 100.0 + d} for d in range(1, 11)]


def fake_news(ticker, limit=5):
    if ticker == "QUIET":
        return []
    return [{"title": f"{ticker} headline {i}", "publisher": "Test Wire",
             "link": "https://example.com", "published": None} for i in range(4)]


def fake_events(ticker):
    from datetime import date, timedelta
    if ticker == "CRASH":
        return {"ticker": ticker,
                "next_earnings_date": str(date.today() + timedelta(days=3)),
                "ex_dividend_date": None}
    return {"ticker": ticker, "next_earnings_date": None, "ex_dividend_date": None}


# --- a fake Anthropic client -----------------------------------------
# Stubbing the client rather than the functions that call it means the
# prompt-assembly code still runs and gets tested -- and we can count how
# many model calls a page costs, which is a design claim worth asserting.
class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_Block(text)]


class _Messages:
    def __init__(self, themes_text=None):
        self.calls = []
        self.themes_text = themes_text or (
            '[{"theme": "Memory selloff", "what": "Several memory names fell together on '
            'the same export rule.", "tickers": ["MU", "WDC"]}]'
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        system = kwargs.get("system", "")
        if "JSON array" in system:
            return _Response(self.themes_text)
        return _Response("Stubbed model output.")


class FakeClient:
    def __init__(self, themes_text=None):
        self.messages = _Messages(themes_text)


FAKE_MOVERS = [
    # good candidates, market-wide
    {"ticker": "SURGE", "name": "Surge Inc", "price": 88.0, "change_percent": 7.1,
     "market_cap": 40e9, "screens": ["day_gainers"]},
    {"ticker": "MU", "name": "Micron", "price": 141.0, "change_percent": -8.4,
     "market_cap": 150e9, "screens": ["day_losers", "most_actives"]},
    # already on the watchlist -- must not be re-suggested
    {"ticker": "CRASH", "name": "Crash Co", "price": 100.0, "change_percent": -6.0,
     "market_cap": 30e9, "screens": ["day_losers"]},
    # junk that must be filtered out
    {"ticker": "PENNY", "name": "Penny Co", "price": 1.2, "change_percent": 240.0,
     "market_cap": 50e9, "screens": ["day_gainers"]},
    {"ticker": "TINY", "name": "Tiny Co", "price": 40.0, "change_percent": 60.0,
     "market_cap": 100e6, "screens": ["day_gainers"]},
]


def fake_movers(*args, **kwargs):
    return [dict(m) for m in FAKE_MOVERS]


def fake_market_news(*args, **kwargs):
    return [{"title": "Chip export rules widen", "publisher": "Reuters",
             "link": "https://example.com", "related_tickers": ["MU"]}]


def fake_earnings(ticker):
    from datetime import date, timedelta
    schedule = {
        "CRASH": 3,     # this week
        "QUIET": 12,    # next week
        "SPY": None,    # no date
    }
    days = schedule.get(ticker, 40)
    if days is None:
        return {"ticker": ticker, "next_date": None, "days_away": None,
                "eps_estimate": None, "last_report": None}
    return {
        "ticker": ticker,
        "next_date": (date.today() + timedelta(days=days)).isoformat(),
        "days_away": days,
        "eps_estimate": 2.15,
        "last_report": {"date": "2026-06-11", "eps_estimate": 1.90,
                        "eps_actual": 2.05, "surprise_percent": 7.9},
    }


def fake_quarters(ticker, quarters=6):
    if ticker not in KNOWN:
        return []
    return [
        {"period": f"2025-{m:02d}-30", "revenue": 1.0e9 + m * 1e8,
         "net_income": 2.0e8 + m * 1e7, "net_margin": 20.0 + m}
        for m in (3, 6, 9, 12)
    ]


def fake_stats(ticker):
    return {"market_cap": 1.2e12, "trailing_pe": 28.4, "forward_pe": 24.1,
            "profit_margin_percent": 23.5, "revenue_growth_percent": 8.2,
            "sector": "Technology", "name": ticker}


def install_stubs():
    # app.py did `from tools.market_data import ...`, so the names live in
    # the app module's namespace -- that's what has to be replaced.
    server.get_stock_price = fake_price
    server.get_price_history = fake_history
    server.get_recent_news = fake_news
    server.get_upcoming_events = fake_events
    server.analyze = lambda ticker, data: "Stubbed analysis."
    server.load_watchlist = lambda: ["QUIET", "CRASH"]
    server.save_watchlist = lambda tickers: None
    server.client = FakeClient()
    server.get_market_movers = fake_movers
    server.get_market_news = fake_market_news
    server.get_earnings_schedule = fake_earnings
    server.get_quarterly_results = fake_quarters
    server.get_key_stats = fake_stats
    server._cache.clear()


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def main() -> int:
    install_stubs()
    client = server.app.test_client()
    failures = 0

    print("\nAttention scoring")
    crash = server.compute_attention(fake_price("CRASH"), fake_news("CRASH"),
                                     fake_events("CRASH"), 0.2)
    quiet = server.compute_attention(fake_price("QUIET"), fake_news("QUIET"),
                                     fake_events("QUIET"), 0.2)
    failures += not check("a 6% drop before earnings scores higher than a flat quiet name",
                          crash["score"] > quiet["score"], f"{crash['score']} vs {quiet['score']}")
    failures += not check("that name is flagged high attention", crash["level"] == "high", crash["level"])
    failures += not check("the quiet name is flagged quiet", quiet["level"] == "quiet", quiet["level"])
    failures += not check("relative-to-market factor is surfaced",
                          any("vs market" in f["label"] for f in crash["factors"]),
                          str(crash["factors"]))
    failures += not check("earnings proximity is surfaced",
                          any("earnings" in f["label"] for f in crash["factors"]),
                          str(crash["factors"]))

    print("\nRanking")
    server._cache.clear()
    rows = client.get("/api/watchlist/data").get_json()["rows"]
    failures += not check("watchlist is sorted by attention, not alphabetically",
                          [r["ticker"] for r in rows] == ["CRASH", "QUIET"],
                          str([r["ticker"] for r in rows]))

    print("\nRoutes")
    for path in ["/", "/static/style.css", "/static/app.js", "/api/overview", "/api/watchlist"]:
        res = client.get(path)
        failures += not check(f"GET {path} returns 200", res.status_code == 200, str(res.status_code))

    server._cache.clear()
    detail = client.get("/api/stock/CRASH").get_json()
    failures += not check("detail view returns price, history, news and analysis",
                          all(k in detail for k in ("price", "history", "news", "analysis")),
                          str(list(detail)))
    failures += not check("detail view includes market comparison",
                          detail.get("market") is not None)

    print("\nFailure handling")
    server._cache.clear()
    bad = client.get("/api/stock/NOSUCH").get_json()
    failures += not check("an unknown ticker degrades instead of 500ing",
                          "price_error" in bad and bad.get("history") == [])
    missing = client.get("/api/search?q=NOSUCH").get_json()
    failures += not check("search reports no results cleanly",
                          missing["results"] == [] and "message" in missing)


    print("\nDaily brief")
    server._cache.clear()
    server.client = FakeClient()
    brief = client.get("/api/brief").get_json()
    failures += not check("brief returns text and a timestamp",
                          brief.get("brief") and brief.get("generated_at"))
    failures += not check("the whole list costs exactly ONE model call",
                          len(server.client.messages.calls) == 1,
                          f"{len(server.client.messages.calls)} calls")
    sent = server.client.messages.calls[0]["messages"][0]["content"]
    failures += not check("both watchlist names reach the prompt",
                          "CRASH" in sent and "QUIET" in sent)
    failures += not check("the brief prompt forbids giving advice",
                          "no buy/sell/hold" in server.BRIEF_SYSTEM.lower())

    print("\nDiscover -- market-wide scan")
    server._cache.clear()
    server.client = FakeClient()
    disc = client.get("/api/discover").get_json()
    tickers = [r["ticker"] for r in disc["rows"]]
    failures += not check("surfaces market-wide names, not just a fixed list",
                          "SURGE" in tickers and "MU" in tickers, str(tickers))
    failures += not check("never re-suggests something already on the watchlist",
                          "CRASH" not in tickers, str(tickers))
    failures += not check("filters out sub-$5 stocks however big the move",
                          "PENNY" not in tickers, str(tickers))
    failures += not check("filters out sub-$2B companies",
                          "TINY" not in tickers, str(tickers))
    failures += not check("reports the scan source and size",
                          disc.get("source") == "screener" and disc.get("scanned") == 5,
                          f"{disc.get('source')} / {disc.get('scanned')}")

    print("\nThemes")
    failures += not check("themes are parsed into structured objects",
                          disc["themes"] and disc["themes"][0]["theme"] == "Memory selloff",
                          str(disc.get("themes")))
    failures += not check("themes carry their tickers",
                          "MU" in disc["themes"][0]["tickers"], str(disc["themes"][0]))
    server.client = FakeClient(themes_text="I'm afraid I can't do that.")
    failures += not check("malformed theme JSON degrades to no themes, not a crash",
                          server.extract_themes([{"ticker": "MU"}], []) == [])
    server.client = FakeClient(themes_text='```json\n[{"theme":"Fenced","what":"x","tickers":[]}]\n```')
    fenced = server.extract_themes([{"ticker": "MU"}], [])
    failures += not check("code-fenced JSON is still parsed",
                          fenced and fenced[0]["theme"] == "Fenced", str(fenced))

    print("\nDegradation")
    server._cache.clear()
    server.client = FakeClient()
    server.get_market_movers = lambda *a, **k: []
    fb = client.get("/api/discover").get_json()
    failures += not check("falls back to a fixed list when the scanner fails",
                          fb.get("source") == "fallback", str(fb.get("source")))
    server.get_market_movers = fake_movers

    print("\nBrief covers beyond the watchlist")
    server._cache.clear()
    server.client = FakeClient()
    client.get("/api/brief")
    sent_brief = server.client.messages.calls[0]["messages"][0]["content"]
    failures += not check("market-wide movers reach the brief prompt",
                          "market_wide_movers_not_owned" in sent_brief and "SURGE" in sent_brief)
    failures += not check("market headlines reach the brief prompt",
                          "Chip export rules widen" in sent_brief)
    failures += not check("the brief still costs exactly one model call",
                          len(server.client.messages.calls) == 1,
                          f"{len(server.client.messages.calls)} calls")

    print("\nEarnings calendar")
    server._cache.clear()
    cal = client.get("/api/earnings").get_json()
    labels = [g["label"] for g in cal["groups"]]
    failures += not check("groups by proximity, soonest first",
                          labels[0] == "This week", str(labels))
    failures += not check("a date 12 days out lands in 'Next week'",
                          "Next week" in labels, str(labels))
    first_group = cal["groups"][0]["items"]
    failures += not check("the imminent name is in the first group",
                          first_group[0]["ticker"] == "CRASH", str(first_group[0]["ticker"]))
    failures += not check("last quarter's surprise comes through",
                          first_group[0]["last_report"]["surprise_percent"] == 7.9)
    failures += not check("recent quarterly revenue is attached",
                          len(first_group[0]["recent_quarters"]) == 4)
    failures += not check("bucketing puts an unscheduled name last",
                          server._bucket(None) == "No date scheduled")
    failures += not check("a past date is treated as unscheduled, not 'this week'",
                          server._bucket(-5) == "No date scheduled")

    print("\nFundamentals on the detail view")
    server._cache.clear()
    det = client.get("/api/stock/CRASH").get_json()
    failures += not check("detail carries quarterly results",
                          len(det.get("quarters", [])) == 4, str(len(det.get("quarters", []))))
    failures += not check("detail carries key stats",
                          det.get("stats", {}).get("trailing_pe") == 28.4)
    failures += not check("detail carries the earnings schedule",
                          det.get("earnings", {}).get("days_away") == 3)
    server._cache.clear()
    broken = client.get("/api/stock/NOSUCH")
    body = broken.get_json()
    failures += not check("one failing sub-fetch doesn't take down the whole page",
                          broken.status_code == 200 and "price_error" in body
                          and body.get("quarters") == [] and "analysis" in body,
                          f"status={broken.status_code} keys={sorted(body)[:8]}")

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
