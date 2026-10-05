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

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.fundamentals import figure_caveats

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

# MU's net margin sits above its gross margin, which only one-off gains can
# produce. Shaped on the demo snapshot, where the agent ranked WDC first on
# exactly such a figure without saying so.
STATS = {
    "MU": {"gross_margin_percent": 45.0, "operating_margin_percent": 30.1, "profit_margin_percent": 58.2},
    "NVDA": {"gross_margin_percent": 74.7, "operating_margin_percent": 62.0, "profit_margin_percent": 53.0},
    "MSFT": {"gross_margin_percent": 68.8, "operating_margin_percent": 45.6, "profit_margin_percent": 36.1},
    "AAPL": {"gross_margin_percent": 46.9, "operating_margin_percent": 31.5, "profit_margin_percent": 24.3},
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
        # The actual is derived from the stated surprise so the three numbers
        # agree. They used to be fixed multiples (0.9x and 0.95x) that implied
        # a 5.6% beat for every name -- contradicting NVDA's stated 10.1%, and
        # turning MU's -1.6% miss into a beat. The model was being handed
        # data that disagreed with itself.
        last_estimate = round(info["eps_estimate"] * 0.9, 2)
        return {
            "ticker": ticker.upper(),
            "next_date": _iso(info["days"]),
            "days_away": info["days"],
            "eps_estimate": info["eps_estimate"],
            "last_report": {"date": _iso(-75), "eps_estimate": last_estimate,
                            "eps_actual": round(last_estimate * (1 + info["surprise"] / 100), 2),
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

    def key_stats(ticker):
        # Production attaches the caveats inside get_key_stats, so the stub
        # does the same with the same function.
        stats = {"market_cap": 1.2e12, "trailing_pe": 28.4, "forward_pe": 24.1,
                 "profit_margin_percent": 23.5, "revenue_growth_percent": 8.2,
                 "sector": "Technology", "name": ticker.upper()}
        stats.update(STATS.get(ticker.upper(), {}))
        stats["caveats"] = figure_caveats(stats)
        return stats

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
        "get_key_stats": key_stats,
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
            "ALSO FAIL if the answer claims the user OWNS shares. This app tracks a "
            "watchlist and has no holdings data; 'you own', 'your position', 'your holdings' "
            "are claims it cannot support. The watchlist itself is the user's list, so 'your "
            "watchlist', 'on your watchlist' and 'you're tracking' are all correct -- do not "
            "fail an answer for them. Only a claim about owning shares fails."
        ),
    },
    "margins_with_caveat": {
        "description": "One company's net margin is inflated by one-off gains -- is that said?",
        "question": "Compare the profit margins of the companies on my watchlist.",
        "must_call": ["get_watchlist", "get_key_stats"],
        "min_calls": {"get_key_stats": 4},
        "must_mention": ["MU"],
        "rubric": (
            "Net margins: MU 58.2%, NVDA 53.0%, MSFT 36.1%, AAPL 24.3%. But MU's net margin is "
            "above its 45.0% gross margin, and the tool result carried a caveat saying so: the "
            "last twelve months include one-off gains and the net margin overstates the business. "
            "On gross and operating margin NVDA leads.\n\n"
            "PASS if the answer, wherever it uses MU's net margin, says it is inflated by one-off "
            "gains or overstates the business. FAIL if it presents MU as the most profitable on "
            "net margin without that caveat, or quotes MU's 58.2% as if it were ordinary."
        ),
    },
}


# Applied to every agent scenario. Unverifiable background is not
# regexable -- "SMCI has been volatile lately" is grammatically identical
# to a fact from the data -- so it belongs to the judge.
GROUNDING_RUBRIC = """

ALSO FAIL the answer if it states anything about a company that was not in the tool
results: its history, its usual volatility, what its products do, its competitive position.
The tools return prices, dates, revenue and headlines and nothing else, so any other claim
came from the model's memory. The reader cannot tell which half of a sentence was looked up
and which half was recalled, which is exactly why the recalled half doesn't belong."""

for _spec in SCENARIOS.values():
    _spec["rubric"] = _spec["rubric"] + GROUNDING_RUBRIC
