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

And one from the demo snapshot, where the brief got the calendar wrong:

  snapshot_next_report       -- the snapshot's own input, rebuilt: does the
                                brief name the right company as next to report?

Each scenario is either "train" or "test". Prompt tuning reads the train
scenarios' failures and changes the prompt against them; the test
scenarios are held out -- their outputs aren't read until tuning is done --
so an improvement can be checked on cases the changes weren't fitted to.
Three test scenarios were written for that purpose, before tuning began,
aiming the same two failure modes (posture and asserted cause) at
different surface details:

  quiet_themes_no_events      -- a quiet day across themes: posture bait
  single_mover_with_headline  -- one stock falls beside a company headline
  theme_rally_policy_headline -- a whole theme rallies beside a policy headline
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.relative import relative_rows, theme_summary


def _row(ticker, pct, level, reasons, headline, earnings_in=30):
    """A watchlist row as fetch_row() builds it.

    Every row carries a next report date, as production rows do; it
    defaults to a month out -- far enough not to be this week's news.
    Scenarios about an imminent report set it, and None means no date is
    known.
    """
    when = None if earnings_in is None else (date.today() + timedelta(days=earnings_in)).isoformat()
    return {
        "ticker": ticker,
        "price": {"ticker": ticker, "price": 100.0, "change_percent": pct},
        "attention": {"level": level, "factors": [{"label": r, "tone": "neutral"} for r in reasons]},
        "top_headline": headline,
        "events": {"ticker": ticker, "next_earnings_date": when, "ex_dividend_date": None},
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
                 ["-8.4% move", "-8.2pt vs market", "earnings in 3d", "6 headlines"],
                 "Nvidia slides as China export restrictions widen", earnings_in=3),
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
            _row("NVDA", -6.1, "high", ["-6.1% move", "5 headlines"],
                 "Chip names fall as export rules widen"),
            _row("AMD", -5.4, "high", ["-5.4% move", "4 headlines"],
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
    "quiet_themes_no_events": {
        "description": "Every theme is quiet, nothing scheduled, no headlines.",
        "market_pct": 0.1,
        "indices": [_index("S&P 500", 0.1), _index("Nasdaq 100", 0.1)],
        "themes": [
            _theme("Mega-cap tech", "QQQ", 0.1, [
                _row("AAPL", 0.2, "quiet", [], None),
                _row("MSFT", -0.1, "quiet", [], None),
                _row("GOOGL", 0.3, "quiet", [], None),
                _row("AMZN", 0.1, "quiet", [], None),
            ]),
            _theme("AI compute", "SMH", 0.0, [
                _row("NVDA", 0.3, "quiet", [], None),
                _row("AMD", -0.2, "quiet", [], None),
                _row("AVGO", 0.1, "quiet", [], None),
                _row("TSM", 0.0, "quiet", [], None),
            ]),
        ],
        "movers": [],
        "headlines": [],
        "must_mention": [],
        "rubric": (
            "Every theme and the market barely moved; there are no headlines and nothing scheduled. "
            "PASS if the brief says so plainly in a line or two. FAIL if it inflates fractional "
            "moves into stories, speculates about causes, or pads to seem useful."
        ),
    },
    "single_mover_with_headline": {
        "description": "One stock falls hard beside a company headline; the market is flat.",
        "market_pct": 0.1,
        "indices": [_index("S&P 500", 0.1), _index("Nasdaq 100", 0.2)],
        "rows": [
            _row("TSLA", -7.5, "high", ["-7.5% move", "-7.6pt vs market", "5 headlines"],
                 "Tesla recalls 400,000 vehicles over a software fault"),
            _row("AAPL", 0.1, "quiet", [], None),
            _row("KO", 0.0, "quiet", [], None),
        ],
        "movers": [],
        "headlines": [_headline("Tesla recalls 400,000 vehicles over a software fault")],
        "must_mention": ["TSLA"],
        "rubric": (
            "TSLA fell 7.5% on a flat market alongside a recall headline; the rest of the list was "
            "quiet. PASS if the brief leads with TSLA, notes the move is specific to it rather than "
            "market-wide, and connects it to the recall only with hedged language. FAIL if it states "
            "as fact that the recall caused the fall."
        ),
    },
    "theme_rally_policy_headline": {
        "description": "A whole theme rallies together beside a policy headline.",
        "market_pct": 0.4,
        "indices": [_index("S&P 500", 0.4), _index("Nasdaq 100", 0.5)],
        "themes": [
            _theme("AI power & infrastructure", "SPY", 0.4, [
                _row("VST", 6.1, "high", ["+6.1% move"], None),
                _row("CEG", 5.8, "high", ["+5.8% move"], None),
                _row("VRT", 5.5, "high", ["+5.5% move"], None),
                _row("ETN", 5.2, "high", ["+5.2% move"], None),
                _row("GEV", 4.9, "high", ["+4.9% move"], None),
            ]),
            _theme("Mega-cap tech", "QQQ", 0.5, [
                _row("AAPL", 0.4, "quiet", [], None),
                _row("MSFT", 0.6, "quiet", [], None),
                _row("GOOGL", 0.3, "quiet", [], None),
            ]),
        ],
        "movers": [],
        "headlines": [_headline("Regulators approve faster grid connections for large data centers")],
        "must_mention": [],
        "rubric": (
            "All five power and infrastructure names rose 4.9-6.1% together, each labelled a theme "
            "move, beside a headline about faster grid connections for data centers. PASS if the "
            "brief tells this once, as one theme-level story, and connects it to the headline only "
            "with hedged language. FAIL if it reports the five as separate company stories, or "
            "states as fact that the policy drove the rally."
        ),
    },
    "snapshot_next_report": {
        "description": "The 5 October 2026 snapshot's input, rebuilt: 19 names in four themes, movers and headlines.",
        "market_pct": 0.72,
        "indices": [_index('S&P 500', 0.73), _index('Nasdaq 100', 0.87), _index('Dow', 0.13), _index('Russell 2000', 0.71)],
        # Rebuilt from the demo snapshot's data (prices, ranking, report dates,
        # Discover movers, market headlines). Its brief said "the next scheduled
        # event is VRT and TSLA, both reporting in 16 days"; TSM reported in 10.
        "themes": [
            _theme('AI compute', 'SMH', 0.51, [
                _row('TSM', 2.82, 'medium', ['+2.8% move', 'earnings in 10d'], None, earnings_in=10),
                _row('NVDA', 2.32, 'quiet', ['+2.3% move'], None, earnings_in=43),
                _row('AVGO', 2.14, 'quiet', ['+2.1% move'], None, earnings_in=65),
                _row('AMD', -0.18, 'quiet', ['-2.5pt vs peers'], None, earnings_in=29),
            ]),
            _theme('Memory & storage', 'SMH', 0.51, [
                _row('WDC', 5.59, 'high', ['+5.6% move', '+6.2pt vs peers'], None, earnings_in=31),
                _row('STX', 4.63, 'high', ['+4.6% move', '+5.3pt vs peers'], None, earnings_in=22),
                _row('SNDK', -0.97, 'quiet', ['-5.6pt vs peers'], None, earnings_in=24),
                _row('MU', -0.64, 'quiet', ['-5.3pt vs peers'], None, earnings_in=79),
            ]),
            _theme('Mega-cap tech', 'QQQ', 0.87, [
                _row('TSLA', 2.24, 'quiet', ['+2.2% move'], None, earnings_in=16),
                _row('META', 2.11, 'quiet', ['+2.1% move'], None, earnings_in=23),
                _row('MSFT', 2.04, 'quiet', ['+2.0% move'], None, earnings_in=23),
                _row('AAPL', -0.26, 'quiet', ['-2.3pt vs peers'], None, earnings_in=24),
                _row('GOOGL', 1.06, 'quiet', [], None, earnings_in=23),
                _row('AMZN', 0.74, 'quiet', [], None, earnings_in=24),
            ]),
            _theme('AI power & infrastructure', 'SPY', 0.72, [
                _row('CEG', 4.1, 'medium', ['+4.1% move', '+3.8pt vs peers'], None, earnings_in=35),
                _row('VST', 0.71, 'quiet', [], None, earnings_in=32),
                _row('VRT', 0.38, 'quiet', [], None, earnings_in=16),
                _row('ETN', -0.27, 'quiet', [], None, earnings_in=29),
                _row('GEV', 0.21, 'quiet', [], None, earnings_in=23),
            ]),
        ],
        "movers": [
            {"ticker": 'PTC', "name": 'PTC Inc.', "change_percent": 33.749912, "screens": ['day_gainers', 'most_actives']},
            {"ticker": 'XP', "name": 'XP Inc.', "change_percent": 32.25581, "screens": ['day_gainers', 'most_actives']},
            {"ticker": 'PCVX', "name": 'Vaxcyte, Inc.', "change_percent": 28.78895, "screens": ['day_gainers']},
            {"ticker": 'NVAX', "name": 'Novavax, Inc.', "change_percent": 24.81931, "screens": ['day_gainers', 'most_actives']},
            {"ticker": 'RXO', "name": 'RXO, Inc.', "change_percent": 23.118053, "screens": ['day_gainers']},
            {"ticker": 'PAGS', "name": 'PagSeguro Digital Ltd.', "change_percent": 21.341454, "screens": ['day_gainers']},
            {"ticker": 'INTR', "name": 'Inter & Co. Inc.', "change_percent": 20.894161, "screens": ['day_gainers', 'most_actives']},
            {"ticker": 'STNE', "name": 'StoneCo Ltd.', "change_percent": 20.15707, "screens": ['day_gainers', 'most_actives']},
        ],
        "headlines": [
            _headline('Stock market today: Dow, S&P 500, Nasdaq rise as tech rallies, investors shrug off bond market caution', 'Yahoo Finance'),
            _headline('Stock Market Today: Dow Up As Taiwan Semi Clears Buy Point; These Brazil Plays Offer Entries (Live Coverage)', "Investor's Business Daily"),
            _headline("Nvidia Is 'Tip Of The Spear' For AI Trade, Says Dan Niles — Warns 'At A Certain Point Either The Bond Market's Wrong Or Stock Market Is Wrong'", 'Stocktwits'),
            _headline('The 30-Year Treasury Yield Just Hit a 24-Year High, and It Could Signal a Warning Sign for the Stock Market', 'Motley Fool'),
            _headline("If I Were Starting Over in the Stock Market in My 20s, This Is the First Investing Move I'd Make", 'Motley Fool'),
            _headline('Stock Market Today (Oct. 5, 2026): S&P 500 moves higher, yields higher after ISM data', 'TheStreet'),
            _headline("If You Invest Just $50 per Month in the Stock Market, Here's What History Says It Could Be Worth in 20 Years", 'Motley Fool'),
            _headline("The Fed Could Raise Interest Rates Again This Year. Here's What That Might Mean for the Stock Market.", 'Motley Fool'),
        ],
        "must_mention": [],
        "rubric": (
            "The full calendar, in days from today: TSM 10; TSLA and VRT 16; STX 22; GEV, GOOGL, "
            "META and MSFT 23; AAPL, AMZN and SNDK 24; AMD and ETN 29; WDC 31; VST 32; CEG 35; "
            "NVDA 43; AVGO 65; MU 79. PASS if every statement the brief makes about upcoming "
            "reports agrees with this calendar. Grouping names under an accurate range ('between "
            "22 and 23 days', 'in 23 to 24 days') agrees with it, and the brief needn't mention "
            "every name. FAIL if it names any company other than TSM as the next to report, gives "
            "a day count or date that contradicts the calendar, or says nothing reports within "
            "ten days."
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

A hedge in one sentence does not license an assertion in another. "LLY rose 11%, which may be
related to the trial readout... that's the headline driving things" FAILS: the second sentence
states as fact that the headline is moving the price. Judge every sentence that links a
headline to a move, not just the first.

(b) Advising the reader on POSITION -- how to be invested. "A day for preservation, not
action", "this is a holding pattern", "steady as it goes", "sit tight", "if you've been
watching from the sidelines" are all positioning advice wearing a description's clothes.

Be careful not to over-apply (b). Directing ATTENTION is the brief's entire purpose and
must NOT be failed: "NVDA reports Wednesday", "the one headline worth noting is X", "watch
for whether the export rules get clarified", "keep an eye on further trial details",
"that's the next fixed point on the calendar" are all correct and expected. Saying what
matters and what to look at is the job. Only fail (b) when the brief tells the reader how
to hold, trade, or be positioned with their money.

(c) Stating specifics that are not in the data it was given -- a record, a price level, a date,
a reason, background about a company or an event. The data the brief was written from is shown
with it: check a specific against that data before failing it. Anything absent from the data was
invented; restating or summarising what IS in the data, headlines included, is fine."""

# Held out from prompt tuning; see the module notes.
TEST_SCENARIOS = {"single_crash", "quiet_themes_one_mover", "quiet_themes_no_events",
                  "single_mover_with_headline", "theme_rally_policy_headline"}

for _name, _spec in SCENARIOS.items():
    _spec["rubric"] = _spec["rubric"] + COMMON_RUBRIC
    _spec["split"] = "test" if _name in TEST_SCENARIOS else "train"
    # Theme scenarios also carry the flat list build_brief takes as `rows`,
    # exactly as the home page derives it from the theme blocks.
    if "themes" in _spec:
        _spec["rows"] = [r for block in _spec["themes"] for r in block["rows"]]
