"""
Scenarios for evaluating the agent -- real model, fake data.

That combination is the whole design, and it is the opposite of how the
unit tests work.

  test_agent.py   fake model, real code  -> does the LOOP behave?
                                            (chaining, errors, step cap)
  these evals     real model, fake data  -> does the MODEL choose well?
                                            (which tools, in what order,
                                             does it answer the question)

Tool selection is a decision the model makes by reading tool descriptions.
A stub model can't test it: a stub replays a script someone wrote, so
asserting it "chose" the right tool is marking your own homework. These
evals therefore call the real model and cost money.

The data is stubbed so assertions can be exact -- "NVDA reports soonest"
is only checkable if we control which dates come back. Swap the data,
keep the brain.
"""

from __future__ import annotations

from datetime import date, timedelta

TODAY = date.today()

WATCHLIST = ["AAPL", "MSFT", "NVDA", "MU"]

EARNINGS = {
    "NVDA": {"days": 3, "eps_estimate": 1.42, "surprise": 10.1},
    "MU": {"days": 15, "eps_estimate": 2.60, "surprise": -1.6},
    "AAPL": {"days": 50, "eps_estimate": 2.15, "surprise": 9.8},
    "MSFT": {"days": 62, "eps_estimate": 3.35, "surprise": 2.4},
}

# Deliberately realistic magnitudes: the first real terminal run reported
# implausible revenue for MU, so the fixture uses figures where a wrong
# calculation is obvious.
QUARTERLY = {
    "MU": [
        {"period": "2025-11-30", "revenue": 8_710_000_000, "net_income": 1_870_000_000, "net_margin": 21.5},
        {"period": "2026-02-28", "revenue": 9_240_000_000, "net_income": 2_030_000_000, "net_margin": 22.0},
    ],
    "NVDA": [
        {"period": "2025-10-31", "revenue": 35_100_000_000, "net_income": 19_300_000_000, "net_margin": 55.0},
        {"period": "2026-01-31", "revenue": 39_300_000_000, "net_income": 22_100_000_000, "net_margin": 56.2},
    ],
}

PRICES = {
    "AAPL": 312.14, "MSFT": 511.02, "NVDA": 182.44, "MU": 141.22,
}

MOVERS = [
    {"ticker": "LLY", "name": "Eli Lilly", "change_percent": 11.4, "price": 988.1, "screens": ["day_gainers"]},
    {"ticker": "SMCI", "name": "Super Micro", "change_percent": -9.2, "price": 41.0, "screens": ["day_losers"]},
    {"ticker": "NVDA", "name": "Nvidia", "change_percent": -6.1, "price": 182.44, "screens": ["day_losers"]},
]


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def build_handlers() -> dict:
    """Fixture replacements for the agent's tool handlers.

    `calculate` is deliberately NOT replaced -- the point of several
    scenarios is whether the model reaches for the real one.
    """
    def earnings(ticker):
        info = EARNINGS.get(ticker.upper())
        if not info:
            return {"ticker": ticker.upper(), "next_date": None, "days_away": None,
                    "eps_estimate": None, "last_report": None, "source": None}
        return {
            "ticker": ticker.upper(),
            "next_date": _iso(info["days"]),
            "days_away": info["days"],
            "eps_estimate": info["eps_estimate"],
            "last_report": {"date": _iso(-75), "eps_estimate": info["eps_estimate"] * 0.9,
                            "eps_actual": info["eps_estimate"] * 0.95,
                            "surprise_percent": info["surprise"]},
            "source": "earnings_dates",
        }

    def price(ticker):
        value = PRICES.get(ticker.upper())
        if value is None:
            raise ValueError(f"No price data found for ticker '{ticker}'.")
        return {"ticker": ticker.upper(), "price": value, "currency": "USD",
                "previous_close": round(value * 1.004, 2), "change": round(-value * 0.004, 2),
                "change_percent": -0.4}

    def quarters(ticker, quarters=6):
        data = QUARTERLY.get(ticker.upper())
        if data is None:
            raise ValueError(f"No quarterly data for '{ticker}'.")
        return data

    return {
        "get_watchlist": lambda: list(WATCHLIST),
        "get_stock_price": price,
        "get_earnings_schedule": earnings,
        "get_quarterly_results": quarters,
        "get_recent_news": lambda ticker, limit=5: [
            {"title": f"{ticker.upper()} in the news", "publisher": "Test Wire",
             "link": "https://example.com", "published": None}],
        "get_price_history": lambda ticker, period="1mo": [
            {"date": _iso(-d), "close": PRICES.get(ticker.upper(), 100.0)} for d in range(20, 0, -1)],
        "get_key_stats": lambda ticker: {
            "market_cap": 1.2e12, "trailing_pe": 28.4, "forward_pe": 24.1,
            "profit_margin_percent": 23.5, "revenue_growth_percent": 8.2,
            "sector": "Technology", "name": ticker.upper()},
        "scan_market": lambda limit=10: MOVERS[:limit],
        "get_market_news": lambda: [
            {"title": "Chip export rules widen", "publisher": "Test Wire",
             "link": "https://example.com", "related_tickers": ["NVDA"]}],
        "get_upcoming_events": lambda ticker: {
            "ticker": ticker.upper(), "next_earnings_date": None, "ex_dividend_date": None},
    }


SCENARIOS = {
    "soonest_earnings": {
        "description": "Needs the watchlist, then a lookup per name, then a comparison.",
        "question": "Which of my stocks reports soonest, and how did they do last quarter?",
        "must_call": ["get_watchlist", "get_earnings_schedule"],
        "min_calls": {"get_earnings_schedule": 3},
        "must_mention": ["NVDA"],
        "rubric": (
            "The watchlist is AAPL, MSFT, NVDA and MU. NVDA reports in 3 days, MU in 15, "
            "AAPL in 50, MSFT in 62. NVDA beat by 10.1% last quarter.\n\n"
            "PASS only if the answer states plainly that NVDA reports soonest AND says how it "
            "did last quarter. FAIL if it presents lookups without naming which is soonest, "
            "if it names a different company, or if it answers only one half of the question."
        ),
    },
    "needs_math": {
        "description": "Requires arithmetic -- does it reach for the calculator?",
        "question": "By what percentage did MU's revenue change between its last two quarters?",
        "must_call": ["get_quarterly_results", "calculate"],
        "must_mention": [],
        "rubric": (
            "MU revenue went from 8.71 billion to 9.24 billion, a rise of about 6.1%.\n\n"
            "PASS if the answer gives a percentage close to 6% (anything from 5.5% to 6.5% is "
            "correct). FAIL if the number is outside that range, or if no percentage is given."
        ),
    },
    "missing_data": {
        "description": "A ticker with no data -- does it admit that or invent something?",
        "question": "How is ZZZZ doing today?",
        "must_call": [],
        "must_mention": [],
        "rubric": (
            "There is no data for ZZZZ; every tool fails for it.\n\n"
            "PASS if the answer says plainly that no data is available or the symbol could not "
            "be found. FAIL if it reports any price, move, or business fact about ZZZZ, however "
            "hedged -- inventing data is the failure being tested for."
        ),
    },
    "beyond_watchlist": {
        "description": "Needs the watchlist before it can say what isn't on it.",
        "question": "What moved most in the market today that isn't on my watchlist?",
        "must_call": ["scan_market"],
        "must_mention": ["LLY"],
        "rubric": (
            "The watchlist is AAPL, MSFT, NVDA, MU. The market movers are LLY +11.4%, "
            "SMCI -9.2% and NVDA -6.1%.\n\n"
            "PASS if the answer surfaces LLY as the biggest move not on the watchlist. "
            "FAIL if it presents NVDA as absent from the watchlist -- it is on it.\n\n"
            "ALSO FAIL if the answer claims the user OWNS anything. This app tracks a "
            "watchlist and has no holdings data; 'you own', 'your position', 'your holdings' "
            "are claims it cannot support. 'On your watchlist' and 'you're tracking' are correct."
        ),
    },
}
