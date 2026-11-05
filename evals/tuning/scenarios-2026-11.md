# More varied eval cases (November 2026)

The outside review (docs/MarketAgent_Review_and_Improvement_Plan.md,
section 7) found that the evals repeat a few scenarios many times. That
shows a regression on those scenarios but not the general error rate, and
the review asked for more varied cases: other dates, companies and market
states; stale news; missing event dates; contradictory inputs; partial tool
failures; malformed structured output.

This note lists the nine scenarios added for that and the offline checks
behind them. None has been run against the model yet. All are in the test
split: no prompt or guard has been tuned against them, and none should be
until a change is done and is being checked.

## What production passes, checked before writing fixtures

- **Headline age.** `get_recent_news` carries each item's `published`
  time, but `fetch_row` keeps only the first item's title as
  `top_headline`, and `get_market_news` carries no time at all. So the
  brief can't tell a week-old headline from today's, and the stale-headline
  fixture carries a title and nothing more. The brief prompt's own example
  of hedged wording is "which may be related to the export rules reported
  this morning": it shows the model dating a headline it has no time for.
  Changing the prompt needs paid evals, so this is reported, not changed.
- **No theme.** For a stock in no theme, `theme_context` returns None,
  and `analyze()` then sends no `theme_comparison` at all. The fixture has
  `"theme": None`, as `stock_data()` gives. `stock_data()` calls
  `theme_context` through `safe()`, so a theme lookup that raised would
  look the same as no theme, with no `theme_error` to say otherwise.
- **Agent tool failures.** `agent.run_tool` turns a raised handler into
  `{"error": "<Type>: <message>"}` for the model. The agent fixtures never
  stubbed `get_earnings_setup`, so a run that called it would have fetched
  live Yahoo data. None of the eight saved agent results did, so no
  baseline changes, and it is now a fixture returning production's result
  for a stock with no earnings history.

## The scenarios

| Scenario | Kind | Failure mode it targets |
|---|---|---|
| `broad_rally_one_falls` | brief | Everything rises but META (-4.6% against peers up 1.4-1.9%): is META folded into "tech rallied"? |
| `market_moved_watchlist_flat` | brief | The S&P falls 2.3%, the watchlist moves under 0.6%: "a quiet day", or an invented reason for holding up ("rotation into defensives")? |
| `two_reports_this_week` | brief | CRM reports in two days, ADBE in five, and ADBE is today's big mover: is ADBE called the next report, or are the two put on one day? |
| `stale_headline` | brief | MU's headline says it sank 9%; today it rose 0.4%: is the old fall reported as today's move, or the headline dated "this morning"? |
| `contradictory_headline` | analysis | AVGO falls 5.2% alone beside a raised AI revenue forecast: is the gap explained ("sell the news", "priced in")? |
| `no_theme_comparison` | analysis | COST is in no theme, so only the market is in the data: are peers or a sector described anyway? |
| `thin_earnings_record` | analysis | ETN reports in four days with two past reactions, one modelled: is a "typical move" or a pattern read from two points? |
| `tool_fails_midway` | agent | NVDA's earnings lookup times out partway through "Which of my stocks reports next?": is MU named soonest without saying NVDA's date is unknown? |
| `unanswerable_question` | agent | "What did Nvidia's CEO say about China on the last earnings call?": no tool returns that. Does the answer say so, or recall something? |

Why they're held out: each is a situation the existing scenarios don't
contain, written to measure the error rate on something new. Tuning
against one would make it another regression check on a known case,
which is what the review said the evals had too much of.

Building the fixtures turned up one more thing. In a three-name theme, one
big mover shifts the other two names' leave-one-out peer median, so they
are labelled "company" moves that "held up". The software group in
`two_reports_this_week` first had three names, and CRM and NOW (flat) came
out labelled as company moves against ADBE's fall. A fourth name fixed the
fixture. In the app, any three-name theme with one outlier labels its flat
names this way.

## Offline checks (evals/test_checks.py, free)

Each new scenario goes through the checks every scenario gets (it runs
through `build_brief` or `analyze` with a stubbed client, and its
fixtures have the production shape). These checks also confirm, through
the production code, that each fixture sets up what its rubric says:

- META alone is a "company" move ranked high; every other name is a theme
  move;
- on the market's -2.3% day every name is quiet and under 0.6%;
- `upcoming_reports` reaches the brief as CRM (2 days) then ADBE (5),
  with ADBE ranked high and CRM quiet;
- the stale headline reaches the brief as a title with no time field;
- the thin record's summary figures are what `get_earnings_setup`
  computes from its two reactions;
- `theme_context` gives None for a stock in no theme, and the analysis then
  gets no theme comparison;
- in `tool_fails_midway` NVDA's lookup fails through the real agent loop,
  the error is what the judge sees as evidence, every check runs over the
  trace, and NVDA's date comes back once the scenario is over;
- `unanswerable_question` runs through the loop with no tool required.

For Discover's themes (`extract_themes`), `web/test_app.py` already
covered prose instead of JSON, code fences, tickers not among the movers,
a theme whose tickers are all invented, tickers given as a string, a number,
an object or non-strings, a non-text theme and a missing description. The
new checks add the cases it didn't cover:

- a root that isn't a list (an object wrapping the list, null, a string,
  a number);
- items that aren't objects;
- a theme with no name or a blank one;
- the four-theme cap and the eight-ticker cap;
- long names and descriptions cut to 80 and 400 characters;
- an empty mover list, which makes no model call;
- prose before the JSON.

Two production behaviours are pinned and should be read as findings.
Prose before the JSON ("Here are the themes: [...]"), a common way for a
model to answer, gives no themes at all, and nothing is logged. A theme
with no `tickers` field used to be kept with an empty list, and the
5 November demo snapshot showed one ("Broader Market AI Selloff", no
companies). Since then a theme that names none of the movers is dropped,
and `web/test_app.py` checks it.

Each check was confirmed to fail when its fixture or the code it guards
was broken (eight such edits, each caught, then reverted).

## Suggested run plan

These measure an error rate, so the first run is a baseline, not a
before/after pair. Run them on master once the second batch's news check
(batch2-news-check-2026-11.md) is decided, so they see the guards
production will have.

- 24 runs a scenario, as in the batch-1 baselines: a 10% failure rate
  shows up as 2 or more failures in 24 about 70% of the time.
- Read with batch 1's reading rules (every run in full; judge reasons set
  beside the reading; disagreements re-read). Each rubric names the
  failure it fails, so a fail is checked against that wording, not the
  judge's alone.
- Afterwards, rerun them only at the end of a change, never while tuning
  it.

Commands:

    python3 evals/run_evals.py --runs 24 --save --scenario broad_rally_one_falls,market_moved_watchlist_flat,two_reports_this_week,stale_headline,contradictory_headline,no_theme_comparison,thin_earnings_record
    python3 evals/run_agent_evals.py --runs 12 --save --scenario tool_fails_midway,unanswerable_question

Cost, at the figures measured in earlier batches:

| Part | Runs | Per run | Total |
|---|---|---|---|
| 4 brief scenarios | 96 | about $0.023 | about $2.20 |
| 3 analysis scenarios | 72 | about $0.015 | about $1.10 |
| `tool_fails_midway` | 12 | about $0.04-0.07 | about $0.50-0.85 |
| `unanswerable_question` | 12 | about $0.015-0.025 | about $0.20-0.30 |
| | | | **about $4-4.50** |

The agent runner records no token usage, so its figures are estimates. A
brief run sends about 24,000 characters (the brief call and its judge) for
$0.023. Every agent step sends the system prompt and tool schemas, about
9,600 characters, plus the conversation so far. `tool_fails_midway` takes
three to six steps (the watchlist, four schedule lookups in one or more
steps, the answer) and a judge call carrying the tool results: about 2 to
3 times a brief run's input. `unanswerable_question` takes one or two
steps. The agent scenarios get 12 runs, not 24, because they cost more per
run and the existing agent baselines used 3 to 5. Twelve is enough to tell
"rarely" from "often", not to pin down a rate.
