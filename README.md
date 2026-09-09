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

### The agent, and how a tool gets connected

`agent.py` is the conversational half — ask it anything and it decides
which tools to call. It now has ten, including the market scanner, the
earnings schedule and company financials, so it can answer questions that
need several lookups chained: *"which of my stocks reports soonest, and how
did they do last quarter?"* takes the watchlist, then each name's schedule,
then a comparison.

Connecting a tool has exactly three parts, and the surprising one is the
second:

1. **A plain Python function.** The code in `tools/` knows nothing about
   Claude and never has.
2. **A JSON schema** — name, plain-language description, arguments. This is
   *the only thing the model ever sees.* It cannot read your source. It
   decides whether a tool is relevant purely by reading that description,
   which makes writing descriptions prompt engineering rather than
   documentation. "Get events" and "Get the next scheduled earnings date,
   the analyst EPS estimate, and whether the company beat last quarter"
   produce very different behaviour from the identical function.
3. **A dispatch table** mapping the schema name back to the real function,
   so something actually runs when the model asks.

In `agent.py` all three live in one `TOOLS` entry per tool, so adding a
capability is a single edit rather than three that can silently drift apart.

Two robustness details worth stealing: a tool that raises returns its error
*as data* the model can explain, rather than crashing the program; and the
loop has a step cap, because a model that keeps calling tools and never
answers will otherwise burn tokens until you kill it.

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

### Starting it without the terminal

Double-click `start.command` in Finder. It activates the virtualenv,
starts the server and opens the browser for you. Closing the window stops
it. (macOS may ask you to confirm the first time, since it's a script you
downloaded rather than an app — right-click → Open once, then double-click
works from then on.)

### Tests, and the two kinds of them

There are two categories here and the distinction matters more than it
looks.

**Free, offline, instant** — run these constantly:

```bash
python3 web/test_app.py        # dashboard: scoring, filtering, routes, degradation
python3 test_agent.py          # agent loop: chaining, errors, runaway protection
python3 evals/test_checks.py   # the eval checks themselves
```

None of these touch the network or call a model. They stub everything, so
they're fast and can't fail because Yahoo rate-limited you — a test that
fails for reasons unrelated to your code teaches you nothing. Stubbing also
lets you construct exact scenarios ("a stock down 6% with earnings in three
days") that you could never arrange with live data.

That third suite exists because **a check suite that always passes is worse
than none** — it hands you confidence you haven't earned. So it feeds
deliberately bad output through the checks and asserts they FAIL.

**Costs money, calls the real model** — run these when you change a prompt:

```bash
python3 evals/run_evals.py            # every scenario, once
python3 evals/run_evals.py --runs 3   # three times each, for variance
python3 evals/run_evals.py --dry-run  # exercise the harness, no API calls
```

### Evals — testing the part that isn't deterministic

Everything above tests code that either works or doesn't. Evals test the
writing, which is the only part of this that's actually AI. Without them
the brief could drift into giving investment advice, or miss the one thing
that mattered, and nothing would catch it — you'd find out by reading it.

Four scenarios, each built around a specific failure mode: does it
manufacture drama on a quiet day, does it find the single name that
matters, does it see a sector selloff as one story rather than three, does
it look beyond the watchlist when something bigger happened elsewhere.

Checks come in two kinds, and the split is the important idea. **Cheap
checks** are regex and string work — did it name the ticker, did it avoid
every phrasing that would make it advice, is it the right shape. Free,
instant, completely reliable. **Expensive checks** need judgement ("did it
identify the right thing as most important?"), so a second model call
grades the output against a written rubric. That judge is slower, costs
money, and is itself fallible — which is exactly why anything regexable
gets regexed instead. The judge also fails *closed*: an unparseable or
errored verdict counts as a failure, never a pass.

The themes eval carries one check worth copying into any project that
groups things: **no invented tickers**. The model is handed a set of names
and asked to cluster them, and the tempting failure is to add a plausible
peer that was never in the input. That's the hallucination shape this
feature actually has, so that's what gets tested.

**On variance:** a single run is an anecdote, not a measurement. The same
prompt can pass once and fail the next time. When you change a prompt and
want to know whether it genuinely improved, use `--runs 3` or more and
compare pass *rates*, not single outcomes.

For that to work, **check labels must be stable across runs** — the label
is the aggregation key. An early version put the measured value into the
label (`reasonable length (got 823 chars)`, and the judge's reason), so
every run produced a different key and `--runs 3` printed three separate
lines instead of one pass rate. The check that most needed variance
reporting was precisely the one where it silently didn't work. Labels are
now fixed strings and the varying part is printed separately as detail.

### When to stop tuning

Chasing 100% is a trap. An eval that always passes has stopped telling you
anything, and the way you get there is by loosening rubrics until nothing
can fail — which quietly destroys the thing you built them for.

Read the *shape* of the failures instead of the count:

**0/N — systematic.** Something is genuinely wrong. Usually the rule, not
the model: two scenarios failing every run is what exposed an over-broad
posture rule that was flagging the product's core purpose.

**N/N — passing.** Good, but only meaningful if the check can fail; that's
what `evals/test_checks.py` exists to prove.

**Mixed, on borderline wording — probably noise.** Here you need to know
whether the *brief* varied or the *judge* did, and that's what
`--judge-stability N` answers: it generates one brief and judges that same
fixed text N times. If verdicts differ on identical input, the
disagreement belongs to the judge, and no amount of prompt-tuning on the
brief will settle it.

```bash
python3 evals/run_evals.py --judge-stability 5 --scenario quiet_day
```

There's a catch worth knowing: that command generates a *fresh* brief, so
you get whatever the model wrote this time — rarely the borderline one you
actually wanted to examine. The first real use of it came back 5/5 on a
perfectly clean brief, which proved the judge was consistent but said
nothing about the ambiguous sentence that prompted the question.

So genuinely borderline output gets saved to `evals/borderline/` and
judged as fixed text:

```bash
python3 evals/run_evals.py --judge-stability 5 --scenario quiet_day \
    --text evals/borderline/quiet_day_catalysts.txt
```

Now the input is constant and only the judge varies. A split verdict on
identical text means the *standard* is ambiguous there, and the honest fix
is to sharpen the rubric rather than tune the brief until that phrasing
stops appearing.

A residual failure rate on genuinely ambiguous sentences is healthy. It
means the standard still has teeth.

### What the first real eval run found

Worth recording, because it's what evals are for.

The judge caught one failure: the brief wrote "NVDA took an 8.4% hit **as**
the U.S. expanded chip export restrictions", asserting causation the data
doesn't establish. The same run hedged correctly in a different scenario
("moves that **appear related to** a trial readout") — so the model wasn't
incapable, it was inconsistent, which no single run could have revealed.

Reading the output caught two more the checks missed. **Posture advice**
using no forbidden word — "days like this are about preservation, not
action", "if you've been watching from the sidelines" — and **invented
detail** not present in the input ("precisely what Nvidia uses in its AI
accelerators"). The prompt now bans all three explicitly, with a worked
example of hedged versus asserted causation.

Then a lesson about the checks themselves: the first attempt to catch
posture advice with regex caught *neither* real sentence — one used "from
the sidelines" where the pattern said "on", and the other was not an idiom
at all. Chasing it with patterns overfits to one run; the next says "today
rewards patience" and walks through. So fixed idioms stay in regex and the
general case moved to the judge. **Regex what is fixed, judge what is
not** — and verify new patterns against the actual failing sentences,
plus legitimate ones, so you can see the false-positive rate.

After the prompt fix, `--runs 3` on that scenario passed 3/3.

### Known limits### Known limits

- Free delayed data via yfinance; no intraday streaming, options flow, or
  dark pool data.
- Market open/closed doesn't account for holidays.
- Notes and alerts are not built yet. Real alerts (fire while you're not
  looking) need a background scheduler, not just a web server.
- Discover depends on Yahoo's screener endpoint; if it's unavailable the
  page falls back to a fixed large-cap list and labels itself as such.
- Nothing here is financial advice, and the prompts explicitly forbid the
  model from giving buy/sell/hold opinions or price targets. It describes
  and contextualises; it doesn't recommend.
