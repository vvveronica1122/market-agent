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
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response("Stubbed model output.")


class FakeClient:
    def __init__(self):
        self.messages = _Messages()


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
    server.UNIVERSE = ["CRASH", "QUIET", "SPY", "SURGE", "NOSUCH"]
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

    print("\nDiscover")
    server._cache.clear()
    disc = client.get("/api/discover").get_json()
    tickers = [r["ticker"] for r in disc["rows"]]
    failures += not check("surfaces a notable name that isn't on the watchlist",
                          "SURGE" in tickers, str(tickers))
    failures += not check("never re-suggests something already on the watchlist",
                          "QUIET" not in tickers and "CRASH" not in tickers, str(tickers))
    failures += not check("the big mover outranks the flat one",
                          tickers.index("SURGE") < tickers.index("SPY")
                          if "SPY" in tickers else True, str(tickers))
    failures += not check("silently drops tickers with no data",
                          "NOSUCH" not in tickers, str(tickers))
    failures += not check("discover rows carry the same attention scoring",
                          all("attention" in r for r in disc["rows"]))

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
