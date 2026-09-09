"""
Fixed scenarios to evaluate the AI writing against.

Why fixtures instead of live data: with live data you can never tell
whether the brief changed because you improved the prompt or because the
market moved. Freezing the input is what turns "it seemed better" into a
measurement.

Each scenario is built to catch a specific failure mode:

  quiet_day        -- does it manufacture drama when nothing happened?
  single_crash     -- does it find the one thing that matters?
  sector_selloff   -- does it see one story, or report three separately?
  outside_mover    -- does it look beyond the watchlist when told to?
"""

from __future__ import annotations


def _row(ticker, pct, level, reasons, headline):
    return {
        "ticker": ticker,
        "price": {"ticker": ticker, "price": 100.0, "change_percent": pct},
        "attention": {"level": level, "factors": [{"label": r, "tone": "neutral"} for r in reasons]},
        "top_headline": headline,
    }


def _index(label, pct):
    return {"label": label, "change_percent": pct}


def _headline(title, publisher="Test Wire"):
    """Same shape get_market_news() returns. A fixture that doesn't match
    production shape tests a system that doesn't exist."""
    return {"title": title, "publisher": publisher, "link": "https://example.com",
            "related_tickers": []}


SCENARIOS = {
    "quiet_day": {
        "description": "Nothing is happening. The brief should say so, briefly.",
        "market_pct": 0.08,
        "indices": [_index("S&P 500", 0.08), _index("Nasdaq 100", 0.11)],
        "rows": [
            _row("AAPL", 0.2, "quiet", [], "Apple expands retail hours in Brazil"),
            _row("MSFT", -0.1, "quiet", [], None),
            _row("KO", 0.05, "quiet", [], None),
        ],
        "movers": [],
        "headlines": [],
        "must_mention": [],
        "rubric": (
            "The watchlist barely moved and there is no notable news. A good brief says the day "
            "was quiet in a sentence or two and stops. FAIL it if it inflates a 0.2% move into a "
            "story, speculates about causes for tiny moves, or pads with filler to seem useful."
        ),
    },
    "single_crash": {
        "description": "One name falls hard against a flat market, days before earnings.",
        "market_pct": -0.2,
        "indices": [_index("S&P 500", -0.2), _index("Nasdaq 100", -0.3)],
        "rows": [
            _row("NVDA", -8.4, "high",
                 ["-8.4% today", "-8.2pt vs market", "earnings in 3d", "6 headlines"],
                 "Nvidia slides as China export restrictions widen"),
            _row("AAPL", -0.3, "quiet", [], None),
            _row("KO", 0.1, "quiet", [], None),
        ],
        "movers": [],
        "headlines": [_headline("Chip export rules widen to cover high-bandwidth memory")],
        "must_mention": ["NVDA"],
        "rubric": (
            "NVDA fell 8.4% on a flat market with earnings three days away. A good brief leads "
            "with NVDA, notes the move is company-specific rather than market-wide, and flags the "
            "imminent earnings date as the thing to prepare for. FAIL it if it treats all three "
            "names as equally important, misses the earnings timing, or states the export story "
            "caused the fall as established fact rather than a likely link."
        ),
    },
    "sector_selloff": {
        "description": "Three chip names fall together -- one story, not three.",
        "market_pct": -0.4,
        "indices": [_index("S&P 500", -0.4), _index("Nasdaq 100", -1.2)],
        "rows": [
            _row("NVDA", -6.1, "high", ["-6.1% today", "5 headlines"],
                 "Chip names fall as export rules widen"),
            _row("AMD", -5.4, "high", ["-5.4% today", "4 headlines"],
                 "AMD drops alongside semiconductor peers"),
            _row("MU", -7.2, "high", ["-7.2% today", "6 headlines"],
                 "Micron hit hardest as memory rules tighten"),
            _row("KO", 0.2, "quiet", [], None),
        ],
        "movers": [],
        "headlines": [_headline("Chip export rules widen"),
                      _headline("Semiconductor index posts worst day since March")],
        "must_mention": ["NVDA", "AMD", "MU"],
        "rubric": (
            "Three semiconductor names fell together on the same regulatory news. A good brief "
            "recognises this as ONE sector-wide story rather than three unrelated company events, "
            "and says the common cause explicitly. FAIL it if it walks through each name as a "
            "separate item without connecting them."
        ),
    },
    "outside_mover": {
        "description": "The watchlist is dull but something big happened elsewhere.",
        "market_pct": 0.1,
        "indices": [_index("S&P 500", 0.1)],
        "rows": [
            _row("AAPL", 0.3, "quiet", [], None),
            _row("KO", -0.2, "quiet", [], None),
        ],
        "movers": [
            {"ticker": "LLY", "name": "Eli Lilly", "change_percent": 11.4, "screens": ["day_gainers"]},
            {"ticker": "NVO", "name": "Novo Nordisk", "change_percent": -7.8, "screens": ["day_losers"]},
        ],
        "headlines": [_headline("Late-stage obesity trial readout beats expectations")],
        "must_mention": ["LLY"],
        "rubric": (
            "The user's own holdings did nothing, but LLY rose 11% and its competitor NVO fell 8% "
            "on a drug trial readout. A good brief says the watchlist was quiet and then points to "
            "LLY as the notable thing happening outside it. FAIL it if it ignores the market-wide "
            "movers entirely, or if it recommends buying LLY."
        ),
    },
}


# Applied to every scenario. These two failure modes showed up in real eval
# runs across different scenarios, so they belong everywhere rather than
# being repeated by hand in each rubric.
COMMON_RUBRIC = """

ALSO FAIL the brief for either of these, whatever else it does well:

(a) Asserting causation it wasn't given. It receives headlines and price moves, which show
things happening together. "Fell 8% as/after/because the rules changed" states a link as
fact; "fell 8%, which may be related to the rules reported this morning" does not. The
second is acceptable, the first is not.

(b) Advising the reader on posture, even without naming a trade. "A day for preservation,
not action", "this is a holding pattern", "if you've been watching from the sidelines" are
all positioning advice wearing a description's clothes. Describing what happened and what
is scheduled is fine; telling the reader how to be positioned is not."""

for _spec in SCENARIOS.values():
    _spec["rubric"] = _spec["rubric"] + COMMON_RUBRIC
