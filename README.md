# Market Agent

A small, real, tool-using AI agent: ask it about a stock, and it looks up
live price data, recent news, and upcoming events (like earnings dates)
before answering -- instead of guessing from stale training data.

This project exists to learn, hands-on, how agentic AI apps are actually
built. Everything here is deliberately kept small so the underlying
pattern stays visible.

## What this teaches

- **Tool schemas** -- how you describe a function to an LLM (name,
  description, JSON argument schema) so it can decide when to call it.
  See the `TOOLS` list in `agent.py`.
- **The agentic loop** -- the request/tool-call/tool-result/repeat cycle
  that almost every AI agent is built on, however complex it eventually
  gets. See `ask_agent()` in `agent.py`.
- **Separating tools from the agent** -- `tools/market_data.py` has zero
  knowledge of Claude or the agent loop; it's just plain, testable Python.
  That separation is what makes agents debuggable: you can verify a tool
  works *before* trusting an LLM to call it correctly.
- **Designing for messy/failing data** -- news APIs return inconsistent
  shapes, tickers can be wrong, fields can be missing. The tools return
  errors as data (not crashes) so the agent can explain problems instead
  of falling over.

## Project layout

```
market-agent/
  agent.py              the agent loop + CLI entry point
  tools/
    market_data.py       the three tools: price, news, upcoming events
  test_tools.py           standalone test of the tools (no API key needed)
  requirements.txt
  .env.example             copy to .env and add your real API key
```

## Setup

**1. Get an Anthropic API key**

Go to <https://console.anthropic.com>, sign up/sign in, open **API Keys**,
and create a new key. You'll also need to add a small amount of prepaid
credit under **Billing** to actually make calls (a few dollars covers a
lot of experimentation with this project).

**2. Install dependencies**

Run these in your own Terminal app (not through Claude) from inside this
folder -- Claude's sandboxed tools can reach the Anthropic API but are
deliberately blocked from general package registries like PyPI, so this
one step has to happen in your regular Terminal:

```bash
cd ~/Documents/market-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Add your API key**

```bash
cp .env.example .env
```

Then open `.env` and paste your real key in place of `sk-ant-...`.

## Running it

Make sure your virtualenv is active (`source .venv/bin/activate` if it
isn't already), then:

```bash
# Test the data tools alone, no API key needed:
python test_tools.py AAPL

# Ask about specific tickers:
python agent.py AAPL TSLA

# Or run it interactively:
python agent.py
```

## How it works, in short

1. You ask a question ("what's going on with AAPL?").
2. Claude reads the question plus the list of available tools and decides
   it needs `get_stock_price`, maybe `get_recent_news` too.
3. `agent.py` actually runs those Python functions and sends the results
   back to Claude as a new turn in the conversation.
4. Claude reads the results and writes a final answer grounded in real,
   current data -- then the loop ends.

You can watch this happen: `ask_agent()` prints each tool call as it's
made (`-> calling get_stock_price({'ticker': 'AAPL'})`), so you can see
the agent's reasoning in real time.

## Ideas for where to take this next

Once this is working, here are natural next steps that build on it:

- **More tools**: sector performance, analyst ratings, insider trades,
  broader market indices.
- **Memory**: remember a watchlist across runs (a simple JSON file is
  enough to start) so you don't have to type tickers every time.
- **Scheduling**: run it once a day and save/email yourself a digest.
- **Evals**: write a small set of test questions with expected behavior
  (e.g. "does it call get_stock_price when asked for a price?") to check
  changes don't quietly break things -- this is what separates a hobby
  script from something you'd trust.
- **Guardrails**: this project is read-only (it only looks things up), so
  it's a safe place to practice -- but if you ever add tools that *take
  actions* (placing trades, sending emails), that's where you'd add
  confirmation steps before anything irreversible happens.

## A note on financial use

This is a learning project, not investment advice, and the data sources
(free, unauthenticated Yahoo Finance endpoints via `yfinance`) can be
delayed, incomplete, or occasionally wrong. Don't make real financial
decisions based solely on what it tells you.

## Web dashboard

A local dashboard at `web/app.py`. The organising idea: a watchlist sorted
**by what needs attention today**, not alphabetically. Most finance sites
show fifty numbers at equal visual weight and leave you to work out which
two matter; this one does that ranking for you.

Each name is scored in plain Python on four factors -- size of today's
move, how that move compares to the market (SPY), how close earnings are,
and how much news there is -- then the list is sorted by that score and
the reasons are shown as chips on the row. Clicking a row opens a detail
view with a six-month chart, the AI analysis, headlines and the next
earnings date. Search resolves any ticker, on your list or not.

### The two agent patterns, side by side

Worth comparing `agent.py` and `web/app.py`, because they solve the same
problem differently:

- `agent.py` runs the **full agentic loop** -- Claude sees the tool
  schemas and decides what to call. Right when the request is open-ended
  and you can't know in advance what's needed.
- `web/app.py` calls the tools **directly, in parallel**, because every
  row needs the same four things, and computes the ranking in ordinary
  Python. Claude is used for exactly one job: writing the analysis on the
  detail page.

The general lesson: LLMs make poor sorting functions -- slow, costly, and
inconsistent between runs -- and good explainers. Rank with rules;
interpret with the model.

### Running it

```bash
cd ~/Documents/market-agent
source .venv/bin/activate
pip install -r requirements.txt   # flask, added for the dashboard
python3 web/app.py
```

Open <http://127.0.0.1:5050>. Your watchlist saves to `web/watchlist.json`
(gitignored -- it's per-machine state, not source). Ctrl+C stops it.

### Tests

```bash
python3 web/test_app.py
```

These stub out the market data entirely, so they're fast, need no API key,
and never touch the network. That's deliberate: tests that call a live API
fail when Yahoo rate-limits you, which tells you nothing about your code.
Stubbing also lets us construct exact scenarios -- "a stock down 6% with
earnings in three days" -- and assert the ranking responds correctly, which
you can't arrange with live data.

### Known limits

- Free delayed data via yfinance; no intraday streaming, options flow, or
  dark pool data.
- Market open/closed doesn't account for holidays.
- Notes and alerts are not built yet. Real alerts (fire while you're not
  looking) need a background scheduler, not just a web server.
