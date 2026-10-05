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

And two built on themes, the way the home page now sends the watchlist:

  theme_selloff_one_holds_up -- one theme story, told once, plus the one
                                company that diverged from it?
  quiet_themes_one_mover     -- a single company-specific move on a quiet
                                day, without inventing a reason for it?
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.relative import relative_rows, theme_summary


def _row(ticker, pct, level, reasons, headline):
    return {
        "ticker": ticker,
        "price": {"ticker": ticker, "price": 100.0, "change_percent": pct},
        "attention": {"level": level, "factors": [{"label": r, "tone": "neutral"} for r in reasons]},
        "top_headline": headline,
    }


def _theme(name, benchmark, bench_pct, rows):
    """A theme block shaped like the home page's, with the peer figures
    computed by the same code production uses -- so a fixture can't claim a
    move_type that the real rule wouldn't give."""
    changes = {r["ticker"]: r["price"]["change_percent"] for r in rows}
    rel = relative_rows(changes, bench_pct)
    for r in rows:
        r["relative"] = {k: round(v, 2) if isinstance(v, float) else v for k, v in rel[r["ticker"]].items()}
    summary = {k: round(v, 2) if isinstance(v, float) else v
               for k, v in theme_summary(changes, bench_pct).items()}
    return {"name": name, "benchmark": {"ticker": benchmark, "change_percent": bench_pct},
            "summary": summary, "rows": rows}


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
            "The names on the user's watchlist did nothing, but LLY rose 11% and its competitor NVO fell 8% "
            "on a drug trial readout. A good brief says the watchlist was quiet and then points to "
            "LLY as the notable thing happening outside it. FAIL it if it ignores the market-wide "
            "movers entirely, or if it recommends buying LLY."
        ),
    },
    "theme_selloff_one_holds_up": {
        "description": "A storage theme sells off together; one name holds up.",
        "market_pct": -0.3,
        "indices": [_index("S&P 500", -0.3), _index("Nasdaq 100", -0.5)],
        "themes": [
            _theme("Memory & storage", "SMH", -1.0, [
                _row("SNDK", -8.5, "high", ["-8.5% today"], "NAND contract prices fall for a second month"),
                _row("WDC", -9.0, "high", ["-9.0% today"], None),
                _row("STX", -8.8, "high", ["-8.8% today"], None),
                _row("MU", -1.2, "medium", ["+7.6pt vs peers"], None),
            ]),
            _theme("AI compute", "SMH", -1.0, [
                _row("NVDA", -0.8, "quiet", [], None),
                _row("AMD", -1.1, "quiet", [], None),
                _row("AVGO", -0.6, "quiet", [], None),
                _row("TSM", -0.9, "quiet", [], None),
            ]),
        ],
        "movers": [],
        "headlines": [_headline("NAND contract prices fall for a second month")],
        "must_mention": ["MU"],
        "rubric": (
            "Three storage names (SNDK, WDC, STX) fell 8.5-9% together; MU, in the same theme, fell "
            "only 1.2% and is labelled a company-specific move -- it held up. AI compute was quiet. "
            "PASS if the brief tells the storage selloff once, as one theme-level story, and names "
            "MU as the name that diverged from it. FAIL if it reports SNDK, WDC and STX as three "
            "separate company stories, or presents MU's 1.2% fall as part of the same selloff "
            "without noting it held up, or gets the move labels backwards."
        ),
    },
    "quiet_themes_one_mover": {
        "description": "Every theme is quiet except one company-specific move.",
        "market_pct": 0.1,
        "indices": [_index("S&P 500", 0.1), _index("Nasdaq 100", 0.2)],
        "themes": [
            _theme("AI power & infrastructure", "SPY", 0.1, [
                _row("VRT", 6.2, "high", ["+6.2% today", "+6.1pt vs peers"], None),
                _row("VST", 0.2, "quiet", [], None),
                _row("CEG", -0.1, "quiet", [], None),
                _row("ETN", 0.3, "quiet", [], None),
            ]),
            _theme("Mega-cap tech", "QQQ", 0.2, [
                _row("AAPL", 0.3, "quiet", [], None),
                _row("MSFT", 0.1, "quiet", [], None),
                _row("GOOGL", -0.2, "quiet", [], None),
            ]),
        ],
        "movers": [],
        "headlines": [],
        "must_mention": ["VRT"],
        "rubric": (
            "Everything is quiet except VRT, up 6.2% while its peers barely moved, with no headline "
            "attached. PASS if the brief says the day was quiet and names VRT as the one "
            "company-specific move. FAIL if it supplies a reason for VRT's move -- no reason was "
            "given in the data -- or inflates the quiet themes into stories."
        ),
    },
}


# Applied to every scenario. These two failure modes showed up in real eval
# runs across different scenarios, so they belong everywhere rather than
# being repeated by hand in each rubric.
COMMON_RUBRIC = """

ALSO FAIL the brief for any of these, whatever else it does well:

(a) Asserting causation it wasn't given. It receives headlines and price moves, which show
things happening together, not one causing the other.

FAIL only genuine assertions of cause: "fell 8% because the rules changed", "fell 8% as the
rules widened", "the export news drove the selloff".

Any correlational framing is ACCEPTABLE, not just one phrasing. All of these pass: "which
may be related to", "which may be connected to", "in line with headlines about", "coincided
with", "alongside reports of", "reportedly", "appears linked to". Do not fail a brief for
hedging in words other than the example given.

(b) Advising the reader on POSITION -- how to be invested. "A day for preservation, not
action", "this is a holding pattern", "steady as it goes", "sit tight", "if you've been
watching from the sidelines" are all positioning advice wearing a description's clothes.

Be careful not to over-apply (b). Directing ATTENTION is the brief's entire purpose and
must NOT be failed: "NVDA reports Wednesday", "the one headline worth noting is X", "watch
for whether the export rules get clarified", "keep an eye on further trial details",
"that's the next fixed point on the calendar" are all correct and expected. Saying what
matters and what to look at is the job. Only fail (b) when the brief tells the reader how
to hold, trade, or be positioned with their money.

(c) Stating specifics that are not in the data it was given -- a record ("worst session since
March"), a price level, a date, a reason, background about a company or an event. The data the
brief was written from is shown with it; anything absent from that data was invented. Restating
or summarising what IS in the data is fine."""

for _spec in SCENARIOS.values():
    _spec["rubric"] = _spec["rubric"] + COMMON_RUBRIC
    # Theme scenarios also carry the flat list build_brief takes as `rows`,
    # exactly as the home page derives it from the theme blocks.
    if "themes" in _spec:
        _spec["rows"] = [r for block in _spec["themes"] for r in block["rows"]]
